"""Compare actual isolated image receipts without suppressing residual findings."""

import argparse
import json
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree


def compare_capabilities(baseline, candidate):
    for key in ('canvasPixel', 'webgl', 'pdfTextParsed', 'scannedPdfRejected', 'libxmlRuntime'):
        if key not in baseline or candidate.get(key) != baseline[key]:
            raise ValueError('image capability differs: ' + key)


def scan_delta(baseline, candidate, removed_packages):
    def records(report):
        if 'Results' not in report:
            raise ValueError('missing complete scan inventory')
        return {(v['PkgName'], v['VulnerabilityID'], v['InstalledVersion'], v['Severity']): v
                for r in report['Results'] for v in r.get('Vulnerabilities', [])}

    old, new = records(baseline), records(candidate)
    added, removed = new.keys() - old.keys(), old.keys() - new.keys()
    if any(k[3] in {'HIGH', 'CRITICAL'} for k in added):
        raise ValueError('new high or critical finding')
    if any(k[3] in {'HIGH', 'CRITICAL'} and v.get('FixedVersion') for k, v in new.items()):
        raise ValueError('unremediated fixable high or critical finding')
    if any(k[0] not in removed_packages for k in removed):
        raise ValueError('finding disappeared without package removal')
    return {'removedRecords': len(removed), 'addedRecords': len(added),
            'residualBySeverity': dict(Counter(k[3] for k in new)),
            'residualHighCriticalCves': sorted({k[1] for k in new if k[3] in {'HIGH', 'CRITICAL'}})}


def test_counts(path):
    suites = ElementTree.parse(path).getroot().findall('.//testsuite')
    if not suites or any(int(s.get(k, '0')) for s in suites for k in ('failures', 'errors', 'skipped')):
        raise ValueError('image regression failed, skipped or missing')
    count = sum(int(s.get('tests', '0')) for s in suites)
    if not count:
        raise ValueError('empty image regression')
    return count


def verify_image_identity(report, image):
    metadata = report.get('Metadata', {})
    if (metadata.get('ImageID') != image.get('Id') or metadata.get('DiffIDs') != image.get('RootFS', {}).get('Layers')
            or report.get('ArtifactName') not in image.get('RepoTags', [])):
        raise ValueError('scan image identity does not match the verified runtime image')
    return image['Id']


def compare(root):
    def read(variant, name):
        return json.loads((root / variant / name).read_text())
    baseline = read('baseline', 'runtime.json')
    inventory = read('baseline', 'vulnerabilities.json')
    count = test_counts(root / 'baseline/tests.xml')
    llvm = json.loads((root / 'llvm-plan.json').read_text())
    if (llvm.get('status') != 'blocked' or not llvm.get('planOnly') or llvm.get('removedPackages') != []
            or 'libgbm1' not in llvm.get('blockers', [])):
        raise ValueError('LLVM browser dependency boundary changed; review required')
    result = {'scope': 'native isolated experimental images, not release acceptance',
              'llvmRemoval': llvm, 'variants': {}}
    for variant in ('baseline', 'headless'):
        runtime = read(variant, 'runtime.json')
        scan = read(variant, 'vulnerabilities.json')
        image_id = verify_image_identity(scan, read(variant, 'image.json')[0])
        compare_capabilities(baseline['probe'], runtime['probe'])
        if test_counts(root / variant / 'tests.xml') != count:
            raise ValueError('image test count changed')
        pruning = runtime['pruning']
        names = {p['name'] for p in runtime['packages']}
        if variant == 'headless' and ('libcups2t64' in names or runtime['fullChromiumPresent']):
            raise ValueError('full Chromium/CUPS remained installed')
        result['variants'][variant] = {
            'imageId': image_id, 'testsPassed': count, 'capabilitiesMatch': True, 'pruning': pruning,
            'scan': scan_delta(inventory, scan, set(pruning['removedPackages'])),
        }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = compare(args.directory)
    (args.directory / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
