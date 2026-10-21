from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from extrio.explorer import _fetch_source_sample, _requires_pagination_browser, source_fetch_error
from extrio.harvest import embedded_list_url, looks_like_dynamic_list_shell
from extrio.source_network import SourceResponse


@pytest.mark.asyncio
async def test_verified_static_publisher_snapshot_does_not_run_post_analytics():
    url = 'https://czzx.fudan.edu.cn/cggg/list.htm'
    network = SimpleNamespace(fetch=AsyncMock(return_value=SourceResponse(url, 200, {}, b'<ul>Notices</ul>')))
    browser = SimpleNamespace(arun=AsyncMock())
    sample = await _fetch_source_sample(browser, network, url, object())
    assert sample.html == '<ul>Notices</ul>'
    network.fetch.assert_awaited_once_with(url, respect_robots=True)
    browser.arun.assert_not_awaited()


def test_script_generated_ccgp_pager_requires_browser_list_transport():
    html = '<p class="pager"><a class="next" href="index_1.htm">Next</a><script>Pager({size:9})</script></p>'
    assert _requires_pagination_browser(html, 'http://www.ccgp.gov.cn/cggg/zygg/')
    assert not _requires_pagination_browser(html, 'https://other.test/cggg/zygg/')
    assert not _requires_pagination_browser('<a href="index_1.htm">Next</a>', 'http://www.ccgp.gov.cn/cggg/zygg/')


def test_source_fetch_error_hides_crawler_internals_and_explains_connection_failure() -> None:
    error = source_fetch_error(
        "https://fallback-test.example.gov.cn/notices",
        "Unexpected error at async_crawler_strategy.py:778: Page.goto: net::ERR_CONNECTION_CLOSED",
    )

    assert error.code == "SOURCE_UNREACHABLE"
    assert error.retryable is True
    assert str(error) == (
        "无法访问 Source：fallback-test.example.gov.cn，目标站点在建立连接时关闭了连接。"
        "请确认网址可从当前运行环境访问，并检查网络或代理配置后重试。"
    )
    assert "async_crawler_strategy" not in str(error)


def test_embedded_list_url_accepts_only_same_host_frame() -> None:
    source_url = "http://www.ccgp-beijing.gov.cn/xxgg/A002004index_1.htm"

    assert embedded_list_url(
        '<iframe id="shuju" src="//www.ccgp-beijing.gov.cn/xxgg/sjxxgg/A002004001index_1.htm"></iframe>',
        source_url,
    ) == "http://www.ccgp-beijing.gov.cn/xxgg/sjxxgg/A002004001index_1.htm"
    assert embedded_list_url('<iframe id="shuju" src="https://other.example/list"></iframe>', source_url) is None


def test_dynamic_list_shell_requires_async_loader_and_empty_named_container() -> None:
    assert looks_like_dynamic_list_shell(
        '<ul id="records"></ul><script>$.ajax({url: "/api/records"})</script>'
    )
    assert not looks_like_dynamic_list_shell(
        '<ul id="records"><li><a href="/1">A</a></li></ul><script>$.ajax({url: "/api/records"})</script>'
    )
    assert not looks_like_dynamic_list_shell('<ul id="records"></ul>')
