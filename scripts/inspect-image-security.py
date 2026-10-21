"""Read-only dpkg image diagnostics; never classifies a CVE as resolved."""

import hashlib
import importlib.metadata
import json
import os
import platform
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


PROBE = """
import asyncio, io, json, unicodedata
from lxml import etree, html
from PIL import Image, _imaging
from playwright.sync_api import sync_playwright
from extrio.official_documents import OfficialDocuments
from pypdf import PdfWriter
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
    page.set_content('<h1>bounded fixture</h1>'
        + '<p>Public procurement fixture body with sufficient text for PDF extraction.</p>' * 4
        + '<svg width="10" height="10"><rect width="10" height="10"/></svg><canvas id="canvas" width="4" height="4"></canvas>')
    assert page.locator('h1').inner_text() == 'bounded fixture'
    assert page.evaluate('2 + 2') == 4
    canvas = page.evaluate('''() => {
        const ctx = document.querySelector('#canvas').getContext('2d');
        ctx.fillStyle = 'rgb(180,30,60)'; ctx.fillRect(0,0,4,4);
        return Array.from(ctx.getImageData(0,0,1,1).data);
    }''')
    assert canvas == [180, 30, 60, 255]
    webgl = page.evaluate('''() => {
        const c = document.createElement('canvas'); c.width = 4; c.height = 4;
        const gl = c.getContext('webgl');
        if (!gl) return {available: false};
        gl.clearColor(.25,.5,.75,1); gl.clear(gl.COLOR_BUFFER_BIT);
        const pixel = new Uint8Array(4); gl.readPixels(0,0,1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);
        return {available: true, pixel: Array.from(pixel)};
    }''')
    if webgl['available']:
        assert all(abs(a-b) <= 1 for a,b in zip(webgl['pixel'], [64,128,191,255]))
    canvas_png = page.locator('#canvas').screenshot()
    assert Image.open(io.BytesIO(canvas_png)).convert('RGB').getpixel((1,1)) == (180,30,60)
    screenshot_bytes = len(page.screenshot())
    pdf = page.pdf()
    pdf_bytes = len(pdf)
    assert screenshot_bytes > 0 and pdf_bytes > 0
    browser_path = p.chromium.executable_path
    browser.close()
parsed = asyncio.run(OfficialDocuments.pdf(pdf))
assert parsed['extraction'] == 'text_layer'
assert 'Public procurement fixture body' in unicodedata.normalize('NFKC', parsed['text'])
scanned = io.BytesIO()
writer = PdfWriter(); writer.add_blank_page(width=500, height=500); writer.write(scanned)
try:
    asyncio.run(OfficialDocuments.pdf(scanned.getvalue()))
except ValueError as exc:
    assert 'requires_review' in str(exc)
else:
    raise AssertionError('image-only PDF was accepted')
print(json.dumps({'lxmlVersion': list(etree.LXML_VERSION), 'libxmlRuntime': list(etree.LIBXML_VERSION),
    'libxmlCompiled': list(etree.LIBXML_COMPILED_VERSION), 'extensionPaths': [etree.__file__, _imaging.__file__],
    'browserPath': browser_path, 'screenshotBytes': screenshot_bytes, 'pdfBytes': pdf_bytes,
    'canvasPixel': canvas, 'webgl': webgl, 'pdfTextParsed': True, 'scannedPdfRejected': True}))
"""


def command(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=90, check=True)
    return result.stdout


def inspect():
    if sys.platform != 'linux':
        raise RuntimeError('Run only inside the isolated dpkg candidate image')
    packages = parse_packages(command(['dpkg-query', '-W',
        '-f=${db:Status-Status}\t${binary:Package}\t${Version}\t${Depends}\t${Essential}\n']))
    python_packages = {dist.metadata['Name'].lower().replace('_', '-'): dist.version
                       for dist in importlib.metadata.distributions()}
    if {'crawl4ai', 'nltk'} & python_packages.keys():
        raise RuntimeError('removed browser/NLP dependency is still installed')
    process = subprocess.run([sys.executable, '-c', PROBE], capture_output=True, text=True, timeout=90, check=False,
                             env={**os.environ, 'LD_DEBUG': 'libs', 'DEBUG': 'pw:browser'})
    if process.returncode:
        raise RuntimeError('bounded native/browser probe failed: ' + process.stderr[-3000:])
    probe = json.loads(process.stdout)
    loaded = sorted(set(re.findall(r'calling init:\s+([^\s]+)', process.stderr)))
    launched = sorted(set(re.findall(r'<launching>\s+(/[^\s]+)', process.stderr)))
    if not launched or not all(Path(p).is_file() and p.startswith('/ms-playwright/') for p in launched):
        raise RuntimeError('actual browser executable was not observed')
    executables = sorted(set(launched + ([probe['browserPath']] if Path(probe['browserPath']).is_file() else [])))
    return {
        'schemaVersion': 1, 'appVersion': importlib.metadata.version('extrio-backend'),
        'osRelease': platform.freedesktop_os_release(), 'pythonVersion': platform.python_version(),
        'pythonBaseExecutable': sys._base_executable,
        'uvVersion': command(['uv', '--version']).strip(),
        'pgDumpVersion': command(['pg_dump', '--version']).strip(),
        'lockSha256': hashlib.sha256(Path('/app/backend/uv.lock').read_bytes()).hexdigest(),
        'installedPackages': packages,
        'pythonPackages': python_packages,
        'scope': 'fixed offline HTML/XML/PNG/SVG/PDF fixture; not global unreachability or CVE remediation',
        'globalUnreachabilityProven': False,
        'pruning': json.loads(Path('/usr/local/share/extrio/native-pruning.json').read_text())
            if Path('/usr/local/share/extrio/native-pruning.json').is_file() else None,
        'packages': [p for p in packages if p['name'] in FOCUS or p['name'].startswith('libllvm')],
        'declaredReverseDependencies': {name: reverse_dependencies(packages, name) for name in ('libxml2', 'libcups2t64')},
        'printComponentPaths': {name: Path(name).exists() for name in PRINT_COMPONENTS},
        'probe': probe, 'loadedLibraries': loaded,
        'launchedBrowserPaths': launched, 'fullChromiumPresent': Path(probe['browserPath']).is_file(),
        'ldd': {name: command(['ldd', name]) for name in [*probe['extensionPaths'], *executables]},
    }


if __name__ == '__main__':
    print(json.dumps(inspect(), indent=2))
