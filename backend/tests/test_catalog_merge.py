"""Pure local evidence overlays never rewrite the source ledgers."""

import hashlib
import json
import stat
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from tender_sources.catalog_merge import merge_ledgers  # noqa: E402


def ledger(path, *, results=None, manifest=None):
    manifest = manifest or [
        {
            "entry_id": f"main:{number}",
            "group": "main",
            "row_number": number,
            "entry_url": f"https://example.org/{number}",
            "name": "=unsafe",
            "metadata": {},
        }
        for number in range(2)
    ]
    results = (
        results
        if results is not None
        else {
            row["entry_id"]: {
                "entryId": row["entry_id"],
                "status": "error",
                "reason": "unexpected_error:AttributeError",
                "requests": 1,
                "independentlyTested": True,
            }
            for row in manifest
        }
    )
    state = {
        "version": 1,
        "manifest": manifest,
        "fingerprint": hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "results": results,
        "rowRequests": {identifier: row["requests"] for identifier, row in results.items()},
        "requests": sum(row["requests"] for row in results.values()),
        "bytes": 10,
        "running": [],
        "stopReason": None,
        "startedAt": time.time() - 1,
        "codeSha256": {"runner.py": "a" * 64},
    }
    path.write_text(json.dumps(state))
    return state


def test_overlay_replaces_only_actual_results_and_preserves_history(tmp_path):
    baseline, overlay, output = tmp_path / "baseline.json", tmp_path / "overlay.json", tmp_path / "merged"
    ledger(baseline)
    ledger(
        overlay,
        results={
            "main:0": {
                "entryId": "main:0",
                "status": "sample_readable",
                "reason": "readable",
                "requests": 3,
                "independentlyTested": True,
                "samplingScope": "main_detail_samples",
            }
        },
    )
    original = baseline.read_bytes()
    summary = merge_ledgers(baseline, [overlay], output)
    rows = [json.loads(line) for line in (output / "rows.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["baselineStatus"] == "error"
    assert rows[0]["latestStatus"] == "sample_readable"
    assert rows[1]["latestStatus"] == "error"
    assert len(rows[0]["history"]) == 2
    assert len(rows[1]["history"]) == 1
    assert rows[0]["evidence"]["ledgerSha256"] == hashlib.sha256(overlay.read_bytes()).hexdigest()
    assert summary["physicalRequestsAllBatches"] == 5
    assert summary["overlaidEntryCount"] == 1
    assert baseline.read_bytes() == original
    assert "'=unsafe" in (output / "matrix.csv").read_text()
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())


@pytest.mark.parametrize("mutation", ["fingerprint", "unknown_id", "not_executed", "running", "requests", "time", "inherited_request"])
def test_invalid_overlay_rejected(tmp_path, mutation):
    baseline, overlay = tmp_path / "baseline.json", tmp_path / "overlay.json"
    ledger(baseline)
    state = ledger(overlay)
    if mutation == "fingerprint":
        state["fingerprint"] = "wrong"
    elif mutation == "unknown_id":
        state["results"]["unknown"] = state["results"].pop("main:0")
    elif mutation == "not_executed":
        state["results"]["main:0"]["status"] = "not_executed"
    elif mutation == "running":
        state["running"] = ["main:0"]
    elif mutation == "requests":
        state["requests"] += 1
    elif mutation == "time":
        state["startedAt"] = float("nan")
    else:
        state["results"]["main:0"].update(status="inherited_block", independentlyTested=False)
    overlay.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        merge_ledgers(baseline, [overlay], tmp_path / "merged")


def test_overlay_order_and_inherited_block_are_honest(tmp_path):
    baseline, first, second = (tmp_path / name for name in ["baseline.json", "one.json", "two.json"])
    ledger(baseline)
    ledger(
        first,
        results={
            "main:0": {"entryId": "main:0", "status": "needs_adapter", "reason": "missing_body", "requests": 2, "independentlyTested": True}
        },
    )
    ledger(
        second,
        results={
            "main:0": {
                "entryId": "main:0",
                "status": "inherited_block",
                "reason": "host_blocked:source_connection_failed",
                "requests": 0,
                "independentlyTested": False,
            }
        },
    )
    summary = merge_ledgers(baseline, [first, second], tmp_path / "merged")
    first_row = json.loads((tmp_path / "merged" / "rows.jsonl").read_text().splitlines()[0])
    assert first_row["latestStatus"] == "inherited_block"
    assert first_row["evidence"]["independentlyTested"] is False
    assert len(first_row["history"]) == 3
    assert summary["latestIndependentlyTestedCount"] == 1


def test_output_symlink_repository_and_overwrite_rejected(tmp_path):
    baseline = tmp_path / "baseline.json"
    ledger(baseline)
    output = tmp_path / "merged"
    merge_ledgers(baseline, [], output)
    with pytest.raises(ValueError):
        merge_ledgers(baseline, [], output)
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        merge_ledgers(baseline, [], link / "merged2")
    with pytest.raises(ValueError):
        merge_ledgers(baseline, [], Path(__file__).resolve().parents[2] / "forbidden-merge")


@pytest.mark.parametrize("mutation", ["counter_without_result", "false_readable", "request_cap", "unknown_group", "bad_stop"])
def test_overlay_cannot_invent_readability_or_unattributed_requests(tmp_path, mutation):
    baseline, overlay = tmp_path / "baseline.json", tmp_path / "overlay.json"
    ledger(baseline)
    state = ledger(overlay)
    if mutation == "counter_without_result":
        del state["results"]["main:0"]
    elif mutation == "false_readable":
        state["results"]["main:0"].update(status="sample_readable", independentlyTested=False, requests=0)
        state["rowRequests"]["main:0"] = 0
        state["requests"] -= 1
    elif mutation == "request_cap":
        state["results"]["main:0"]["requests"] = state["rowRequests"]["main:0"] = 13
        state["requests"] = 14
    elif mutation == "unknown_group":
        state["manifest"][0]["group"] = "unknown"
        state["fingerprint"] = hashlib.sha256(
            json.dumps(state["manifest"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    else:
        state["stopReason"] = {"not": "a terminal reason"}
    overlay.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        merge_ledgers(baseline, [overlay], tmp_path / "merged")


def test_full_manifest_with_143_synthetic_retests_keeps_denominator_and_groups(tmp_path):
    manifest = [
        {
            "entry_id": f"{group}:{index}",
            "group": group,
            "row_number": index + 2,
            "entry_url": f"https://example.org/{group}/{index}",
            "name": "synthetic",
            "metadata": {},
        }
        for group, count in [("main", 391), ("review", 973)]
        for index in range(count)
    ]
    baseline, overlay = tmp_path / "baseline.json", tmp_path / "overlay.json"
    ledger(baseline, manifest=manifest)
    selected = [row for row in manifest if row["row_number"] < (56 if row["group"] == "main" else 91)]
    assert len(selected) == 143
    results = {
        row["entry_id"]: {
            "entryId": row["entry_id"],
            "status": "candidate_list",
            "reason": "synthetic_retest",
            "requests": 1,
            "independentlyTested": True,
        }
        for row in selected
    }
    ledger(overlay, manifest=manifest, results=results)
    summary = merge_ledgers(baseline, [overlay], tmp_path / "merged")
    assert summary["inputCount"] == 1364
    assert summary["overlaidEntryCount"] == 143
    assert summary["statuses"] == {"candidate_list": 143, "error": 1221}
    assert summary["groups"]["main"]["statuses"]["candidate_list"] == 54
    assert summary["groups"]["review"]["statuses"]["candidate_list"] == 89
    assert len(summary["revisitedPriorToolGaps"]) == 143
