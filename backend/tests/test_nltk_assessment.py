from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_prerelease_assessment_is_pinned_offline_and_never_promotes_dependencies():
    source = (ROOT / 'scripts/assess-nltk-prerelease.sh').read_text()
    assert 'ba6b259aa94a85168c031ad60e4072538c30b513' in source
    assert '2d401f212e7d872d9349bd43dedcab08bda54a807ce99957569725b567714464' in source
    assert 'sha256sum -c' in source
    assert '--network none' in source and '--read-only' in source
    assert '--cap-drop ALL' in source and '--security-opt no-new-privileges' in source
    assert 'pip install' not in source and 'uv sync' not in source
    assert 'backend/data' not in source and 'type=bind,source=$ROOT,' not in source


def test_nltk_probe_requires_real_guard_refusal_and_positive_roundtrip():
    source = (ROOT / 'scripts/nltk-prerelease-probe.py').read_text()
    assert 'except PermissionError' in source
    assert 'roundTripChecks' in source and 'transitionTrain' in source
    assert 'except Exception' not in source
    assert 'nltk.download(' not in source and 'ENFORCE = False' not in source
