"""Evaluate supported OS experiments without waiving existing or new findings."""

import argparse
import hashlib
import json
import runpy
from collections import Counter
from pathlib import Path

COMMON = runpy.run_path(str(Path(__file__).with_name('compare-slim-images.py')))
HIGH = {'HIGH', 'CRITICAL'}


def records(report):
    results = report.get('Results', [])
    if not results or not any(r.get('Class') == 'os-pkgs' for r in results):
        raise ValueError('missing complete OS scan inventory')
    return [{**v, 'Component': v.get('SrcName') or v['PkgName'], 'Class': r.get('Class')}
            for r in results for v in r.get('Vulnerabilities', [])]


def security_delta(baseline, candidate):
    old, new = records(baseline), records(candidate)
    old_high = {(v['Class'], v['Component'], v['VulnerabilityID']) for v in old if v['Severity'] in HIGH}
    added = [v for v in new if v['Severity'] in HIGH and
             (v['Class'], v['Component'], v['VulnerabilityID']) not in old_high]
    fixable = [v for v in new if v['Severity'] in HIGH and v.get('FixedVersion')]
    blockers = []
    if added:
        blockers.append('new_high_critical')
    if any(v['Severity'] == 'CRITICAL' for v in new):
        blockers.append('critical_remaining')
    if fixable:
        blockers.append('fixable_high_critical')
    return {'residualBySeverity': dict(Counter(v['Severity'] for v in new)),
            'residualHighCriticalCves': sorted({v['VulnerabilityID'] for v in new if v['Severity'] in HIGH}),
            'newHighCritical': added, 'fixableHighCritical': fixable, 'blockers': blockers}


def compare(root, variant):
    def read(name, file):
        return json.loads((root / name / file).read_text())
    control = read('headless', 'runtime.json')
    runtime = read(variant, 'runtime.json')
    scan = read(variant, 'vulnerabilities.json')
    old_scan = read('headless', 'vulnerabilities.json')
    COMMON['verify_image_identity'](old_scan, read('headless', 'image.json')[0])
    image_id = COMMON['verify_image_identity'](scan, read(variant, 'image.json')[0])
    COMMON['compare_capabilities'](control['probe'], runtime['probe'])
    count = COMMON['test_counts'](root / variant / 'tests.xml')
    if count != COMMON['test_counts'](root / 'headless/tests.xml'):
        raise ValueError('image regression count differs')
    version = {'noble': '24.04', 'resolute': '26.04'}[variant]
    os_release, scan_os = runtime['osRelease'], scan['Metadata']['OS']
    if (os_release.get('ID') != 'ubuntu' or os_release.get('VERSION_ID') != version
            or os_release.get('VERSION_CODENAME') != variant or scan_os.get('Family') != 'ubuntu'
            or scan_os.get('Name') != version or scan_os.get('Eosl')):
        raise ValueError('supported OS identity does not match')
    if (runtime['lockSha256'] != control['lockSha256'] or runtime['appVersion'] != control['appVersion']
            or not runtime['pythonVersion'].startswith('3.12.') or runtime['uvVersion'] != control['uvVersion']
            or not runtime['pgDumpVersion'].startswith('pg_dump (PostgreSQL) 16.')):
        raise ValueError('frozen application/Python/uv/PostgreSQL contract differs')
    names = {p['name'] for p in runtime['installedPackages']}
    if (runtime['fullChromiumPresent'] or 'libcups2t64' in names or 'libgbm1' not in names
            or runtime['pruning'].get('removedPackages') != ['libcups2t64']
            or not runtime['pruning'].get('essentialPackagesPreserved')):
        raise ValueError('headless/CUPS/GBM boundary differs')
    result = security_delta(old_scan, scan)
    if any(v['VulnerabilityID'] == 'CVE-2026-6653' for v in records(scan)):
        result['blockers'].append('target_libxml_cve_remaining')
    return {'variant': variant, 'imageId': image_id, 'osRelease': os_release,
            'testsPassed': count, 'capabilitiesMatch': True, 'security': result,
            'eligibleForFurtherReview': not result['blockers'],
            'scope': 'independent experiment, not release acceptance or default image change',
            'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (root / variant).iterdir() if p.name in {
                           'runtime.json', 'image.json', 'vulnerabilities.json', 'tests.xml'}}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('variant', choices=['noble', 'resolute'])
    args = parser.parse_args()
    result = compare(args.directory, args.variant)
    (args.directory / args.variant / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if not result['eligibleForFurtherReview']:
        raise SystemExit('Alternative image security gate blocked; complete findings retained')
