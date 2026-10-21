from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from extrio.source_clients import RestrictedBrowser
from extrio.source_network import SourceNetworkError, SourceResponse


def browser_with_results(*results):
    network = SimpleNamespace(
        check_robots=AsyncMock(),
        fetch=AsyncMock(return_value=SourceResponse("https://example.com/", 200, {}, b"page")),
        target=AsyncMock(), final_urls={},
    )
    browser = RestrictedBrowser(network)
    browser._snapshot = AsyncMock(side_effect=results)
    return browser


def result(*, status=200):
    return SimpleNamespace(status_code=status, redirected_url=None)


@pytest.mark.asyncio
async def test_navigation_timeout_retries_once_without_http_zero():
    timeout = PlaywrightTimeoutError('navigation timeout')
    browser = browser_with_results(timeout, result())
    assert (await browser.arun("https://example.com/", object())).status_code == 200
    assert browser._snapshot.await_count == 2
    assert browser.network.fetch.await_count == 2


@pytest.mark.asyncio
async def test_repeated_navigation_timeout_is_precise_and_bounded():
    timeout = PlaywrightTimeoutError('navigation timeout')
    browser = browser_with_results(timeout, timeout)
    with pytest.raises(SourceNetworkError, match="^browser_navigation_timed_out$"):
        await browser.arun("https://example.com/", object())
    assert browser._snapshot.await_count == 2


@pytest.mark.asyncio
async def test_unclassified_browser_failure_does_not_become_http_zero_or_retry():
    browser = browser_with_results(PlaywrightError('Browser disconnected'))
    with pytest.raises(SourceNetworkError, match="^browser_fetch_failed$"):
        await browser.arun("https://example.com/", object())
    assert browser._snapshot.await_count == 1


@pytest.mark.asyncio
async def test_network_rejection_takes_priority_over_timeout_and_never_retries():
    browser = browser_with_results()
    async def denied(*_args):
        browser.failures.append(SourceNetworkError("host_not_allowed"))
        raise PlaywrightTimeoutError('navigation timeout')
    browser._snapshot.side_effect = denied
    with pytest.raises(SourceNetworkError, match="^host_not_allowed$"):
        await browser.arun("https://example.com/", object())
    assert browser._snapshot.await_count == 1


@pytest.mark.asyncio
async def test_http_rejection_preserves_status():
    browser = browser_with_results(result(status=403))
    with pytest.raises(SourceNetworkError, match="^authentication_or_access_required$"):
        await browser.arun("https://example.com/", object())
    assert browser._snapshot.await_count == 1


@pytest.mark.asyncio
async def test_timeout_retry_cannot_reset_network_budget():
    browser = browser_with_results(PlaywrightTimeoutError('navigation timeout'))
    browser.network.fetch.side_effect = [
        SourceResponse("https://example.com/", 200, {}, b"page"),
        SourceNetworkError("duration_exceeded"),
    ]
    with pytest.raises(SourceNetworkError, match="^duration_exceeded$"):
        await browser.arun("https://example.com/", object())
    assert browser._snapshot.await_count == 1


@pytest.mark.asyncio
async def test_late_route_failure_after_page_close_does_not_pollute_next_attempt():
    browser = browser_with_results()
    page = SimpleNamespace(is_closed=lambda: True)
    class Context:
        route = AsyncMock()
        route_web_socket = AsyncMock()
    context = Context()
    await browser.install_routes(page, context)
    route = SimpleNamespace(
        request=SimpleNamespace(method="GET", url="https://example.com/asset.js",
                                resource_type="script", frame=SimpleNamespace(page=page), is_navigation_request=lambda: False),
        abort=AsyncMock(),
    )
    browser.network.fetch.side_effect = SourceNetworkError("source_request_timed_out")
    await context.route.call_args.args[1](route)
    assert browser.failures == []
    route.abort.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('resource_type', ['image', 'font', 'media', 'script', 'stylesheet', 'fetch', 'xhr', 'document'])
async def test_browser_skips_decorative_media_but_retains_text_rendering_dependencies(resource_type):
    browser = browser_with_results()
    page = SimpleNamespace(is_closed=lambda: False)
    class Context:
        route = AsyncMock()
        route_web_socket = AsyncMock()
    context = Context()
    await browser.install_routes(page, context)
    url = 'https://example.com/asset'
    route = SimpleNamespace(request=SimpleNamespace(method='GET', url=url, resource_type=resource_type,
                            frame=SimpleNamespace(page=page), is_navigation_request=lambda: resource_type == 'document'),
                            abort=AsyncMock(), fulfill=AsyncMock())
    browser.network.fetch.return_value = SourceResponse(url, 200, {}, b'content')
    await context.route.call_args.args[1](route)
    if resource_type in {'image', 'font', 'media'}:
        browser.network.fetch.assert_not_awaited()
        route.abort.assert_awaited_once_with('blockedbyclient')
    else:
        browser.network.fetch.assert_awaited_once()
        route.fulfill.assert_awaited_once()
    assert not browser.failures
