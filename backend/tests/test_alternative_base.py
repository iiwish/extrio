import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def inventory(rows, version='24.04'):
    return {'Metadata': {'OS': {'Family': 'ubuntu', 'Name': version}},
            'Results': [{'Class': 'os-pkgs', 'Vulnerabilities': rows}]}


def finding(cve='CVE-fixture', severity='HIGH', version='1'):
    return {'PkgName': 'libxml2', 'SrcName': 'libxml2', 'VulnerabilityID': cve,
            'InstalledVersion': version, 'Severity': severity}


def test_cross_distribution_comparison_uses_component_cve_not_version_strings():
    compare = runpy.run_path(str(ROOT / 'scripts/compare-base-images.py'))['security_delta']
    old = inventory([finding(version='debian-version')])
    new = inventory([finding(version='ubuntu-version')])
    result = compare(old, new)
    assert result['newHighCritical'] == [] and result['blockers'] == ['high_remaining']
    assert result['residualBySeverity'] == {'HIGH': 1}


@pytest.mark.parametrize('report,reason', [
    (inventory([finding('CVE-new')]), 'new_high_critical'),
    (inventory([finding(severity='CRITICAL')]), 'critical_remaining'),
    (inventory([finding()]), 'high_remaining'),
    (inventory([{**finding(), 'FixedVersion': '2'}]), 'fixable_high_critical'),
])
def test_cross_distribution_gate_preserves_all_unhandled_risks(report, reason):
    compare = runpy.run_path(str(ROOT / 'scripts/compare-base-images.py'))['security_delta']
    result = compare(inventory([finding()]), report)
    assert reason in result['blockers']
    assert sum(result['residualBySeverity'].values()) == 1


@pytest.mark.parametrize('report', [{}, {'Results': []}, {'Results': [{'Class': 'lang-pkgs'}]}])
def test_cross_distribution_gate_rejects_missing_os_inventory(report):
    compare = runpy.run_path(str(ROOT / 'scripts/compare-base-images.py'))['security_delta']
    with pytest.raises(ValueError, match='complete'):
        compare(inventory([]), report)


def test_only_shell_pruning_requires_absence_of_full_browser(tmp_path):
    module = runpy.run_path(str(ROOT / 'scripts/prune-image-runtime.py'))
    scope = module['shell_only_directory'].__globals__
    root = tmp_path / 'browsers'
    (root / 'chromium-1234').mkdir(parents=True)
    with pytest.raises(ValueError, match='full Chromium'):
        scope['shell_only_directory'](root)


def test_alternative_dockerfile_is_pinned_isolated_and_preserves_browser_dependencies():
    source = (ROOT / 'docker/backend-ubuntu.Dockerfile').read_text()
    for version in ('24.04', '26.04'):
        assert f'FROM ubuntu:{version}@sha256:' in source
    assert 'uv:0.12.23@sha256:' in source
    assert 'uv python install 3.12.15' in source
    assert '--only-shell chromium' in source and 'only-shell' in source
    assert 'VERSION_CODENAME' in source and '${UBUNTU_SUITE}-pgdg' in source
    assert '--frozen --no-dev' in source and 'FROM runtime AS verification' in source
    assert '--force' not in source and 'autoremove' not in source
    assert 'pip uninstall --system' not in source and '--break-system-packages' not in source
    assert 'libgbm' not in source and 'libllvm' not in source


def test_base_workflow_retains_full_scans_and_native_capability_gate():
    source = (ROOT / '.github/workflows/image-base.yml').read_text()
    assert 'ubuntu-24.04-arm' in source and 'ubuntu-latest' in source
    assert 'noble' in source and 'resolute' in source
    assert 'ignore-unfixed: false' in source
    assert 'UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL' in source
    assert 'compare-base-images.py' in source
    assert 'push:' not in source and 'packages: write' not in source


def test_noble_uses_vendor_python_without_managed_interpreter_or_pip_overrides():
    source = (ROOT / 'docker/backend-ubuntu.Dockerfile').read_text()
    assert 'UV_PYTHON_PREFERENCE=only-system' in source
    assert 'EXTRIO_PYTHON=/usr/bin/python3.12' in source
    assert 'apt-get install -y --no-install-recommends python3.12' in source
    assert '--python "$EXTRIO_PYTHON"' in source
    assert '--break-system-packages' not in source and 'EXTERNALLY-MANAGED' not in source
