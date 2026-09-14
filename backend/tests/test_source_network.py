import asyncio
import gzip
import socket
import ssl
import time

import httpx
import pytest

from extrio.source_network import FetchBudget, SourceNetwork, SourceNetworkError


def tls_connect_error(reason):
    cause = ssl.SSLError(1, reason)
    cause.reason = reason
    error = httpx.ConnectError("TLS handshake failed")
    error.__cause__ = cause
    return error


@pytest.mark.asyncio
async def test_bad_ecpoint_retries_once_with_verified_tls_and_same_pinned_target(public_dns, monkeypatch):
    clients = []
    requests = []
    original_client = httpx.AsyncClient

    def client(**kwargs):
        clients.append(kwargs)
        return original_client(**kwargs)

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            raise tls_connect_error("BAD_ECPOINT")
        return httpx.Response(200, text="notice")

    monkeypatch.setattr(httpx, "AsyncClient", client)
    network = SourceNetwork({"example.test", "other.test"}, transport=httpx.MockTransport(respond))
    assert (await network.fetch("https://example.test/list")).body == b"notice"
    assert len(clients) == len(requests) == 2
    assert clients[0].get("verify", True) is True
    context = clients[1]["verify"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert context.cert_store_stats()["x509_ca"] > 0
    for options, request in zip(clients, requests, strict=True):
        assert options["trust_env"] is False
        assert options["follow_redirects"] is False
        assert request.url == httpx.URL("https://93.184.216.34/list")
        assert request.headers["host"] == "example.test"
        assert request.extensions["sni_hostname"] == "example.test"
    await network.fetch("https://example.test/next")
    assert len(clients) == 3
    assert clients[2]["verify"] is context
    await network.fetch("https://other.test/")
    assert clients[-1]["verify"] is True
    fresh_network = SourceNetwork({"example.test"}, transport=httpx.MockTransport(respond))
    await fresh_network.fetch("https://example.test/")
    assert clients[-1]["verify"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["CERTIFICATE_VERIFY_FAILED", "WRONG_VERSION_NUMBER", "connection refused"])
async def test_other_connection_errors_do_not_trigger_tls_compatibility(reason, public_dns):
    calls = []

    def respond(request):
        calls.append(request)
        raise tls_connect_error(reason)

    network = SourceNetwork({"example.test"}, transport=httpx.MockTransport(respond))
    with pytest.raises(SourceNetworkError, match="source_connection_failed"):
        await network.fetch("https://example.test/")
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("second_reason", ["BAD_ECPOINT", "CERTIFICATE_VERIFY_FAILED"])
async def test_tls_compatibility_failure_is_bounded(public_dns, second_reason):
    calls = []

    def respond(request):
        calls.append(request)
        raise tls_connect_error("BAD_ECPOINT" if len(calls) == 1 else second_reason)

    network = SourceNetwork({"example.test"}, transport=httpx.MockTransport(respond))
    with pytest.raises(SourceNetworkError, match="source_connection_failed"):
        await network.fetch("https://example.test/")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_tls_compatibility_retry_keeps_request_timeout(public_dns):
    calls = []

    async def respond(request):
        calls.append(request)
        if len(calls) == 1:
            raise tls_connect_error("BAD_ECPOINT")
        await asyncio.sleep(0.2)
        return httpx.Response(200)

    network = SourceNetwork({"example.test"}, request_timeout=0.05, transport=httpx.MockTransport(respond))
    with pytest.raises(SourceNetworkError, match="source_request_timed_out"):
        await network.fetch("https://example.test/")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_declared_redirect_limit_and_request_timeout(public_dns):
    calls = []
    network = SourceNetwork(
        {"example.test"},
        max_redirects=0,
        transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(302, headers={"location": "/next"})),
    )
    with pytest.raises(SourceNetworkError, match="redirect_limit_exceeded"):
        await network.fetch("https://example.test/start")
    assert len(calls) == 1

    async def slow(_request):
        await asyncio.sleep(0.2)
        return httpx.Response(200)

    network = SourceNetwork({"example.test"}, request_timeout=0.01, transport=httpx.MockTransport(slow))
    with pytest.raises(SourceNetworkError, match="source_request_timed_out"):
        await network.fetch("https://example.test/start")


@pytest.mark.asyncio
async def test_declared_request_rate_and_concurrency_are_upper_bounds(public_dns):
    active = maximum = 0
    starts = []

    async def respond(_request):
        nonlocal active, maximum
        starts.append(time.monotonic())
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.04)
        active -= 1
        return httpx.Response(200)

    network = SourceNetwork({"example.test"}, max_concurrency=1, requests_per_second=10, transport=httpx.MockTransport(respond))
    await asyncio.gather(*(network.fetch(f"https://example.test/{index}") for index in range(3)))
    assert maximum == 1
    assert all(b - a >= 0.09 for a, b in zip(starts, starts[1:], strict=False))


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url", ["http://127.0.0.1/", "http://169.254.169.254/", "https://other.test/", "file:///etc/passwd", "https://u:p@example.test/"]
)
async def test_forbidden_targets_never_reach_transport(url, public_dns):
    sent = []
    network = SourceNetwork({"example.test"}, transport=httpx.MockTransport(lambda r: sent.append(r)))
    with pytest.raises(SourceNetworkError):
        await network.fetch(url)
    assert sent == []


@pytest.mark.asyncio
async def test_dns_private_or_mixed_answer_is_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(2, 1, 6, "", (ip, 443)) for ip in ["93.184.216.34", "10.0.0.1"]])
    network = SourceNetwork({"example.test"})
    with pytest.raises(SourceNetworkError, match="network_address_blocked"):
        await network.fetch("https://example.test/")


@pytest.mark.asyncio
async def test_validated_address_is_pinned_with_original_host_and_tls_name(public_dns):
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(200, text="hello")

    network = SourceNetwork({"example.test"}, transport=httpx.MockTransport(respond))
    result = await network.fetch("https://example.test/a")
    assert result.body == b"hello"
    assert sent[0].url.host == "93.184.216.34"
    assert sent[0].headers["host"] == "example.test"
    assert sent[0].extensions["sni_hostname"] == "example.test"


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["https://other.test/", "http://example.test/downgrade", "http://169.254.169.254/latest"])
async def test_redirect_rechecks_boundary_before_second_request(location, public_dns):
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(302, headers={"location": location})

    network = SourceNetwork({"example.test"}, transport=httpx.MockTransport(respond))
    with pytest.raises(SourceNetworkError):
        await network.fetch("https://example.test/")
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_total_decoded_bytes_count_across_pages(public_dns):
    network = SourceNetwork(
        {"example.test"},
        budget=FetchBudget(max_total_bytes=7),
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=b"1234")),
    )
    await network.fetch("https://example.test/a")
    with pytest.raises(SourceNetworkError, match="total_bytes_exceeded"):
        await network.fetch("https://example.test/b")


@pytest.mark.asyncio
async def test_robots_disallow_is_enforced_with_same_guard(public_dns):
    network = SourceNetwork(
        {"example.test"}, transport=httpx.MockTransport(lambda _r: httpx.Response(200, text="User-agent: *\nDisallow: /private"))
    )
    with pytest.raises(SourceNetworkError, match="robots_disallowed"):
        await network.check_robots("https://example.test/private")


@pytest.mark.asyncio
async def test_redirect_to_robots_disallowed_path_is_not_fetched(public_dns):
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(302, headers={"location": "/private"})

    network = SourceNetwork({"example.test"}, transport=httpx.MockTransport(respond))
    with pytest.raises(SourceNetworkError, match="robots_disallowed"):
        await network.fetch("https://example.test/public", respect_robots=True)
    assert "/private" not in paths


@pytest.mark.asyncio
async def test_loopback_requires_explicit_development_opt_in():
    network = SourceNetwork(
        {"127.0.0.1"}, allow_localhost=True, transport=httpx.MockTransport(lambda _r: httpx.Response(200, text="fixture"))
    )
    assert (await network.fetch("http://127.0.0.1:8080/")).body == b"fixture"


@pytest.mark.asyncio
async def test_public_http_can_be_disabled(public_dns):
    network = SourceNetwork({"example.test"}, allow_http=False)
    with pytest.raises(SourceNetworkError, match="https_required"):
        await network.fetch("http://example.test/")


@pytest.mark.asyncio
async def test_gzip_response_is_decoded_with_bounded_output(public_dns):
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield gzip.compress(b"notice" * 2000)

    def respond(_request):
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=Body())

    network = SourceNetwork({"example.test"}, transport=httpx.MockTransport(respond))
    assert (await network.fetch("https://example.test/")).body == b"notice" * 2000
    network = SourceNetwork({"example.test"}, budget=FetchBudget(max_page_bytes=100), transport=httpx.MockTransport(respond))
    with pytest.raises(SourceNetworkError, match="page_bytes_exceeded"):
        await network.fetch("https://example.test/")
