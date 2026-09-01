import pytest

from extrio.security import SourceUrlError, normalize_source_url


def test_normalizes_https_source() -> None:
    value, host = normalize_source_url(" https://EXAMPLE.com/list?q=1 ")
    assert value == "https://example.com/list?q=1"
    assert host == "example.com"


def test_allows_anonymous_public_http_when_risk_policy_is_enabled() -> None:
    value, host = normalize_source_url(
        "http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_1.htm",
        allow_http_public=True,
    )
    assert value == "http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_1.htm"
    assert host == "www.ccgp-beijing.gov.cn"


def test_requires_https_when_an_access_profile_is_present() -> None:
    with pytest.raises(SourceUrlError, match="HTTPS") as raised:
        normalize_source_url(
            "http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_1.htm",
            allow_http_public=True,
            has_access_profile=True,
        )
    assert raised.value.code == "HTTPS_REQUIRED"


def test_only_allows_loopback_http_without_public_risk_policy() -> None:
    assert normalize_source_url("http://127.0.0.1:8000/demo", allow_http_localhost=True)[1] == "127.0.0.1"
    with pytest.raises(SourceUrlError, match="HTTPS") as raised:
        normalize_source_url("http://example.com/list", allow_http_localhost=True)
    assert raised.value.code == "HTTPS_REQUIRED"


def test_rejects_literal_private_network_sources() -> None:
    with pytest.raises(SourceUrlError, match="私有"):
        normalize_source_url("https://169.254.169.254/latest/meta-data")


def test_public_http_policy_does_not_allow_loopback_hosts() -> None:
    with pytest.raises(SourceUrlError, match="私有"):
        normalize_source_url("http://localhost/internal", allow_http_public=True)
