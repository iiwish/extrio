from pathlib import Path

import pytest

from extrio.security import SourceUrlError, normalize_source_url, trusted_client_identity


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


def test_anonymous_http_rejection_message_points_at_the_settings_ui() -> None:
    with pytest.raises(SourceUrlError) as raised:
        normalize_source_url("http://example.com/list")
    assert raised.value.code == "HTTPS_REQUIRED"
    assert raised.value.args[0] == "当前部署未允许匿名 HTTP 来源，请改用 HTTPS；仅在部署配置明确允许时可在 设置 → 采集策略 中启用"


def test_access_profile_https_rejection_message_is_unchanged() -> None:
    with pytest.raises(SourceUrlError) as raised:
        normalize_source_url("http://example.com/list", allow_http_public=True, has_access_profile=True)
    assert raised.value.code == "HTTPS_REQUIRED"
    assert raised.value.args[0] == "配置 AccessProfile 或凭据的来源必须使用 HTTPS"


def test_forwarded_client_identity_requires_explicit_proxy_trust() -> None:
    assert trusted_client_identity("10.0.0.8", "203.0.113.5", 0) == "10.0.0.8"
    assert trusted_client_identity("10.0.0.8", "203.0.113.5", 1) == "203.0.113.5"
    assert trusted_client_identity("10.0.0.8", "203.0.113.5, 192.0.2.10", 2) == "203.0.113.5"
    assert trusted_client_identity("10.0.0.8", "spoofed", 1) == "10.0.0.8"


def test_extrio_does_not_expose_nltk_model_artifact_persistence() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "extrio"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.glob("*.py"))
    assert "import nltk" not in source
    assert "from nltk" not in source
    assert "nltk.data.path" not in source
