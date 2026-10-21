"""Read-only Debian image diagnostics; never classifies a CVE as resolved."""

import importlib.metadata
import json
import os
import re
import subprocess
import sys
from pathlib import Path

FOCUS = {'libxml2', 'libcups2t64', 'bsdutils', 'util-linux', 'perl', 'perl-base', 'libperl5.40', 'postgresql-client-common'}
PRINT_COMPONENTS = ('/usr/sbin/cupsd', '/usr/lib/cups/backend/ipp', '/usr/lib/cups/filter/foomatic-rip',
                    '/usr/bin/foomatic-rip', '/usr/bin/lp', '/usr/bin/lpr')


def parse_packages(output):
    packages = []
    for line in output.splitlines():
        fields = line.split('\t')
        if len(fields) != 5:
            raise ValueError('invalid package inventory')
        status, binary, version, depends, essential = fields
        if status in {'config-files', 'not-installed'}:
            continue
        if status != 'installed' or not binary or not version or essential not in {'', 'yes', 'no'}:
            raise ValueError('invalid package inventory')
        packages.append({'name': binary.partition(':')[0], 'binaryPackage': binary, 'version': version,
                         'depends': depends, 'essential': essential == 'yes'})
    return packages


def reverse_dependencies(packages, target):
    # These are declared alternatives, not a claim that a library was loaded.
    return sorted(p['binaryPackage'] for p in packages if target in re.findall(
        r'(?:^|[,|])\s*([a-z0-9][a-z0-9+.-]*)(?::[a-z0-9-]+)?', p['depends']))


PROBE = '''
import io, json
from lxml import etree, html
from PIL import Image, _imaging
from playwright.sync_api import sync_playwright
assert html.fromstring('<h1>fixture</h1>').text_content() == 'fixture'
parser = etree.XMLParser(resolve_entities=False, no_network=True)
assert etree.fromstring(b'<root><child/></root>', parser).tag == 'root'
image = io.BytesIO()
Image.new('RGB', (2, 2), 'white').save(image, 'PNG')
Image.open(io.BytesIO(image.getvalue())).load()
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
    context = browser.new_context(service_workers='block')
    context.route('**/*', lambda route: route.abort())
    context.route_web_socket('**/*', lambda socket: socket.close())
    page = context.new_page()
    page.set_content('<h1>bounded fixture</h1><svg width="10" height="10"><rect width="10" height="10"/></svg>')
    assert page.locator('h1').inner_text() == 'bounded fixture'
    assert page.evaluate('2 + 2') == 4
    screenshot_bytes, pdf_bytes = len(page.screenshot()), len(page.pdf())
    assert screenshot_bytes > 0 and pdf_bytes > 0
    browser_path = p.chromium.executable_path
    browser.close()
print(json.dumps({'lxmlVersion': list(etree.LXML_VERSION), 'libxmlRuntime': list(etree.LIBXML_VERSION),
    'libxmlCompiled': list(etree.LIBXML_COMPILED_VERSION), 'extensionPaths': [etree.__file__, _imaging.__file__],
    'browserPath': browser_path, 'screenshotBytes': screenshot_bytes, 'pdfBytes': pdf_bytes}))
'''


def command(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=90, check=True)
    return result.stdout


def inspect():
    if sys.platform != 'linux':
        raise RuntimeError('Run only inside the isolated Debian candidate image')
    packages = parse_packages(command(['dpkg-query', '-W',
        '-f=${db:Status-Status}\t${binary:Package}\t${Version}\t${Depends}\t${Essential}\n']))
    process = subprocess.run([sys.executable, '-c', PROBE], capture_output=True, text=True, timeout=90, check=False,
                             env={**os.environ, 'LD_DEBUG': 'libs', 'DEBUG': 'pw:browser'})
    if process.returncode:
        raise RuntimeError('bounded native/browser probe failed: ' + process.stderr[-3000:])
    probe = json.loads(process.stdout)
    loaded = sorted(set(re.findall(r'calling init:\s+([^\s]+)', process.stderr)))
    return {
        'schemaVersion': 1, 'appVersion': importlib.metadata.version('extrio-backend'),
        'scope': 'fixed offline HTML/XML/PNG/SVG/PDF fixture; not global unreachability or CVE remediation',
        'globalUnreachabilityProven': False,
        'packages': [p for p in packages if p['name'] in FOCUS or p['name'].startswith('libllvm')],
        'declaredReverseDependencies': {name: reverse_dependencies(packages, name) for name in ('libxml2', 'libcups2t64')},
        'printComponentPaths': {name: Path(name).exists() for name in PRINT_COMPONENTS},
        'probe': probe, 'loadedLibraries': loaded,
        'ldd': {name: command(['ldd', name]) for name in [*probe['extensionPaths'], probe['browserPath']]},
    }


if __name__ == '__main__':
    print(json.dumps(inspect(), indent=2))
