from datetime import UTC, datetime

import httpx
import pytest

from extrio.source_network import FetchBudget, SourceNetwork, SourceNetworkError, retry_after_seconds


@pytest.mark.parametrize(('header', 'expected'), [('120', 120), ('-1', None), ('bad', None),
    ('Tue, 20 Oct 2026 01:01:01 GMT', 61), ('Mon, 19 Oct 2026 01:00:00 GMT', 0),
    ('99999999999999999999999999', 315360000)])
def test_retry_after_parser(header, expected):
    assert retry_after_seconds(header, now=datetime(2026, 10, 20, 1, tzinfo=UTC)) == expected


async def test_request_limit_includes_robots_and_redirects_and_never_exceeds_cap():
    urls = []

    def response(request):
        urls.append(request.url.path)
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nAllow: /')
        return httpx.Response(302, headers={'location': '/next'})

    network = SourceNetwork({'127.0.0.1'}, allow_localhost=True,
        budget=FetchBudget(max_requests=2), transport=httpx.MockTransport(response))
    with pytest.raises(SourceNetworkError, match='source_request_budget_exceeded'):
        await network.fetch('http://127.0.0.1/start', respect_robots=True)
    assert urls == ['/robots.txt', '/start'] and network.requests_used == 2


async def test_http_429_trips_circuit_without_hidden_retries():
    calls = []

    def response(request):
        calls.append(str(request.url))
        return httpx.Response(429, headers={'retry-after': '7200'}, text='Please wait')

    network = SourceNetwork({'127.0.0.1'}, allow_localhost=True, transport=httpx.MockTransport(response))
    for _ in range(2):
        with pytest.raises(SourceNetworkError, match='source_rate_limited'):
            await network.fetch('http://127.0.0.1/list')
    assert len(calls) == network.requests_used == 1
    assert network.rate_limit_response.body == b'Please wait' and network.retry_after == 7200
