import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/inspect-image-security.py'


def test_package_inventory_preserves_versions_architecture_and_essential():
    module = runpy.run_path(str(SCRIPT))
    rows = module['parse_packages']('installed\tlibxml2:amd64\t2.12.7+really2.9.14\tlibc6 (>= 2.38)\tno\n'
                                    'installed\tbsdutils\t2.41.1\tlibc6 (>= 2.38)\tyes\n')
    assert rows == [
        {'name': 'libxml2', 'binaryPackage': 'libxml2:amd64', 'version': '2.12.7+really2.9.14',
         'depends': 'libc6 (>= 2.38)', 'essential': False},
        {'name': 'bsdutils', 'binaryPackage': 'bsdutils', 'version': '2.41.1',
         'depends': 'libc6 (>= 2.38)', 'essential': True},
    ]


@pytest.mark.parametrize('output', ['libxml2\t1.0\n', 'installed\tlibxml2\t1.0\tlibc6\tmaybe\n'])
def test_malformed_inventory_is_not_silently_accepted(output):
    with pytest.raises(ValueError, match='package inventory'):
        runpy.run_path(str(SCRIPT))['parse_packages'](output)


def test_declared_reverse_dependencies_do_not_claim_optional_alternatives_are_loaded():
    module = runpy.run_path(str(SCRIPT))
    rows = module['parse_packages']('installed\tlibllvm:amd64\t1\tlibxml2 (>= 1) | libxml2-alt, libc6:any\tno\n'
                                    'installed\tanother\t1\tnot-libxml2 (>= 1)\tno\n')
    assert module['reverse_dependencies'](rows, 'libxml2') == ['libllvm:amd64']
    assert module['reverse_dependencies'](rows, 'libc6') == ['libllvm:amd64']
    assert module['reverse_dependencies'](rows, 'libcups2t64') == []


def test_removed_package_records_are_not_reported_as_installed():
    rows = runpy.run_path(str(SCRIPT))['parse_packages'](
        'config-files\told-cups\t1\tlibcups2t64\tno\n'
        'not-installed\tvirtual-package\t\t\t\n')
    assert rows == []


def test_security_diagnostics_are_offline_and_do_not_run_collection_commands():
    source = SCRIPT.read_text()
    assert 'https://' not in source and 'http://' not in source
    assert 'source_rate_limited' not in source and 'Store(' not in source
    workflow = (SCRIPT.parents[1] / '.github/workflows/container.yml').read_text()
    assert 'docker run --rm --network none' in workflow
    assert 'target=/tmp/inspect-image-security.py,readonly' in workflow
