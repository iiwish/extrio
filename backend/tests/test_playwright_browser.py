import asyncio
import importlib.util
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from extrio.source_clients import BrowserSnapshotConfig, RestrictedBrowser

ROOT = Path(__file__).resolve().parents[2]


def test_crawl4ai_and_nltk_are_not_runtime_dependencies():
    project = tomllib.loads((ROOT / 'backend/pyproject.toml').read_text())
    lock = tomllib.loads((ROOT / 'backend/uv.lock').read_text())
    assert any(d.startswith('playwright') for d in project['project']['dependencies'])
    assert not {'crawl4ai', 'nltk'} & {p['name'] for p in lock['package']}
    for name in ('crawl4ai', 'nltk'):
        assert importlib.util.find_spec(name) is None


@pytest.mark.parametrize('failure', [None, RuntimeError('navigation failed'), asyncio.CancelledError()])
async def test_snapshot_installs_routes_before_navigation_and_always_closes_context(failure):
    browser = RestrictedBrowser(SimpleNamespace())
    page = SimpleNamespace(goto=AsyncMock(), content=AsyncMock(return_value='<html>settled</html>'),
                           url='https://example.com/final')
    if failure:
        page.goto.side_effect = failure
    else:
        page.goto.return_value = SimpleNamespace(status=200)
    class Context:
        new_page = AsyncMock(return_value=page)
        close = AsyncMock()
    context = Context()
    browser.browser = SimpleNamespace(new_context=AsyncMock(return_value=context))

    async def install(actual_page, actual_context):
        assert actual_page is page and actual_context is context
        page.goto.assert_not_awaited()

    browser.install_routes = AsyncMock(side_effect=install)
    config = BrowserSnapshotConfig(page_timeout=1234, wait_until='load', delay_before_return_html=0)
    if failure:
        with pytest.raises(type(failure)):
            await browser._snapshot('https://example.com/', config)
    else:
        result = await browser._snapshot('https://example.com/', config)
        assert (result.html, result.redirected_url, result.status_code) == ('<html>settled</html>', page.url, 200)
        page.goto.assert_awaited_once_with('https://example.com/', wait_until='load', timeout=1234)
    options = browser.browser.new_context.call_args.kwargs
    assert options['service_workers'] == 'block' and not options['accept_downloads']
    assert not options['ignore_https_errors']
    assert options['viewport'] == {'width': 1080, 'height': 600}
    context.close.assert_awaited_once()


async def test_browser_cleanup_stops_driver_and_proxy_even_when_browser_close_fails():
    browser = RestrictedBrowser(SimpleNamespace())
    browser.browser = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError('close failure')))
    browser.playwright = SimpleNamespace(stop=AsyncMock())
    browser.server = await asyncio.start_server(lambda _r, w: w.close(), '127.0.0.1', 0)
    with pytest.raises(RuntimeError, match='close failure'):
        await browser.__aexit__(None, None, None)
    browser.playwright.stop.assert_awaited_once()
    assert not browser.server.is_serving()


async def test_failed_browser_launch_stops_driver_and_deny_proxy(monkeypatch):
    driver = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(side_effect=RuntimeError('launch failure'))),
                             stop=AsyncMock())
    monkeypatch.setattr('extrio.source_clients.async_playwright', lambda: SimpleNamespace(start=AsyncMock(return_value=driver)))
    browser = RestrictedBrowser(SimpleNamespace())
    with pytest.raises(RuntimeError, match='launch failure'):
        await browser.__aenter__()
    driver.stop.assert_awaited_once()
    assert not browser.server.is_serving()
