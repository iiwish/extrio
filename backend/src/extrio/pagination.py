"""Read literal navigation targets without executing source JavaScript."""
import json
import re
from urllib.parse import quote, urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag


def navigation_url(anchor: Tag | None, base_url: str) -> str | None:
    if anchor is None or anchor.get('aria-disabled') == 'true' or 'disabled' in anchor.get('class', []):
        return None
    href = str(anchor.get('href', '')).strip()
    static = not href or href.startswith('#') or href.lower().startswith('javascript:')
    if static:
        statement = str(anchor.get('onclick', '')).strip()
        assignment = re.fullmatch(r'(?:window\.)?location\.href\s*=\s*(.+?)\s*;?', statement)
        if not assignment:
            return None
        expression = assignment[1]
        encoded = re.fullmatch(r'encodeURI\(\s*(.+?)\s*\)', expression)
        literal = re.fullmatch(r"'([^'\\\r\n]*)'|\"([^\"\\\r\n]*)\"", encoded[1] if encoded else expression)
        if not literal:
            return None
        href = literal[1] if literal[1] is not None else literal[2]
        if encoded:
            href = quote(href, safe=";/?:@&=+$,-_.!~*'()#")
    if not href or href.startswith('#') or '\\' in href or any(ord(c) < 32 for c in href):
        return None
    try:
        target = urldefrag(urljoin(base_url, href))[0]
        parsed, base = urlsplit(target), urlsplit(base_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return None
        if target == urldefrag(base_url)[0]:
            return None
        if static and (parsed.scheme, parsed.hostname, parsed.port) != (base.scheme, base.hostname, base.port):
            return None
        return target
    except ValueError:
        return None


def pagination_hints(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    hints = []
    for anchor in soup.select('a'):
        label = anchor.get_text(' ', strip=True)
        if 'next' in anchor.get('rel', []):
            selector = 'css:a[rel~="next"]'
        elif label in {'下一页', '下页', 'Next', 'Next page', 'next', 'next page'}:
            selector = f'css:a:-soup-contains({json.dumps(label, ensure_ascii=False)})'
        else:
            continue
        target = navigation_url(anchor, base_url)
        if target:
            hints.append({'selector': selector, 'targetUrl': target, 'label': label})
        if len(hints) == 6:
            break
    return hints
