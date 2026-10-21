import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/prune-image-runtime.py'


def test_removal_plan_accepts_only_explicit_native_packages():
    module = runpy.run_path(str(SCRIPT))
    assert module['removal_plan']('Remv libllvm19 [1:19.1]\nPurg libxml2:amd64 [2.9]\n', set()) == {
        'libllvm19', 'libxml2'}


def test_pruning_never_runs_outside_explicit_disposable_build(monkeypatch):
    monkeypatch.delenv('EXTRIO_DISPOSABLE_IMAGE_BUILD', raising=False)
    with pytest.raises(RuntimeError, match='disposable root build container'):
        runpy.run_path(str(SCRIPT))['prune']('baseline')


@pytest.mark.parametrize('output,essential', [
    ('Remv postgresql-client-16 [16]\n', set()),
    ('Remv libxml2 [2.9]\n', {'libxml2'}),
    ('Remv libc6 [2.41]\n', {'libc6'}),
    ('Inst libxml2 [2.9] (2.15)\n', set()),
    ('not a removal plan', set()),
])
def test_unsafe_or_unknown_removal_plan_fails_closed(output, essential):
    with pytest.raises(ValueError, match='removal plan'):
        runpy.run_path(str(SCRIPT))['removal_plan'](output, essential)


def test_browser_removal_is_confined_to_one_full_chromium_directory(tmp_path):
    module = runpy.run_path(str(SCRIPT))
    root = tmp_path / 'browsers'
    full = root / 'chromium-1234' / 'chrome-linux64' / 'chrome'
    full.parent.mkdir(parents=True)
    full.write_text('fixture')
    assert module['full_browser_directory'](root, full) == full.parents[1]
    with pytest.raises(ValueError, match='browser path'):
        module['full_browser_directory'](root, tmp_path / 'outside' / 'chrome')
    external = tmp_path / 'external'
    external.mkdir()
    (root / 'chromium-5678').symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match='browser path'):
        module['full_browser_directory'](root, root / 'chromium-5678' / 'chrome-linux64' / 'chrome')


def test_experimental_image_does_not_replace_default_or_force_package_removal():
    candidate = (ROOT / 'docker/backend-slim.Dockerfile').read_text()
    assert 'FROM extrio/backend:slim-original AS runtime' in candidate
    assert 'ARG PRUNE_VARIANT=llvm' in candidate
    assert 'FROM runtime AS verification' in candidate
    assert 'uv sync --project backend --frozen' in candidate
    source = SCRIPT.read_text()
    assert '--simulate' in source
    assert '--allow-remove-essential' not in source and '--force-depends' not in source
    assert 'apt-get autoremove' not in source


def test_runtime_harness_never_adopts_existing_resources_or_publisher_samples():
    source = (ROOT / 'scripts/verify-slim-image.sh').read_text()
    assert 'network create --internal' in source
    assert 'label=extrio.image-slim=$PROJECT' in source
    assert 'readonly' in source
    assert 'backend/data' not in source and 'test-data/tender-sources' not in source
    assert 'test_full_backup.py' in source and 'test_official_documents.py' in source
    assert 'pg_isready -h 127.0.0.1 -U postgres' in source
    assert 'test_official_v2.py' in source and 'test_source_samples.py' in source


def test_comparison_fails_on_graphics_regression_or_new_high_findings():
    module = runpy.run_path(str(ROOT / 'scripts/compare-slim-images.py'))
    baseline = {'canvasPixel': [180, 30, 60, 255], 'webgl': {'available': True, 'pixel': [64, 128, 191, 255]},
                'pdfTextParsed': True, 'scannedPdfRejected': True, 'libxmlRuntime': [2, 14, 6]}
    module['compare_capabilities'](baseline, dict(baseline))
    with pytest.raises(ValueError, match='capability'):
        module['compare_capabilities'](baseline, {**baseline, 'webgl': {'available': False}})
    vuln = {'PkgName': 'example', 'VulnerabilityID': 'CVE-fixture', 'InstalledVersion': '1', 'Severity': 'HIGH'}
    def inventory(rows):
        return {'Results': [{'Vulnerabilities': rows}]}
    with pytest.raises(ValueError, match='new high'):
        module['scan_delta'](inventory([]), inventory([vuln]), set())
    with pytest.raises(ValueError, match='without package removal'):
        module['scan_delta'](inventory([vuln]), inventory([]), set())
    assert module['scan_delta'](inventory([vuln]), inventory([]), {'example'})['removedRecords'] == 1
    fixable = {**vuln, 'FixedVersion': '2'}
    with pytest.raises(ValueError, match='fixable high'):
        module['scan_delta'](inventory([fixable]), inventory([fixable]), set())
