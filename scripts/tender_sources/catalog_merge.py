"""Pure local, append-only provenance overlays for isolated catalog ledgers."""

import argparse
import csv
import hashlib
import io
import json
import math
import os
import time
from itertools import pairwise
from pathlib import Path

TERMINAL = {
    "sample_readable",
    "candidate_list",
    "needs_adapter",
    "body_incomplete",
    "restricted",
    "invalid_input",
    "inherited_block",
    "error",
    "budget_exhausted",
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _read(path):
    path = Path(path).absolute()
    if path.is_dir():
        path = path / "ledger.json"
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("symlink input is forbidden")
    raw = path.read_bytes()
    state = json.loads(raw)
    manifest = state.get("manifest")
    if (
        not isinstance(manifest, list)
        or not manifest
        or any(
            not isinstance(row, dict) or row.get("group") not in ("main", "review")
            for row in manifest
        )
        or state.get("fingerprint") != _sha(_json(manifest).encode())
    ):
        raise ValueError("invalid manifest fingerprint")
    identifiers = [row.get("entry_id") for row in manifest]
    if any(not isinstance(value, str) or not value for value in identifiers) or len(
        set(identifiers)
    ) != len(identifiers):
        raise ValueError("invalid manifest IDs")
    results, requests = state.get("results"), state.get("rowRequests")
    if (
        not isinstance(results, dict)
        or not isinstance(requests, dict)
        or state.get("running") != []
    ):
        raise ValueError("ledger is not quiescent")
    if any(identifier not in identifiers for identifier in [*results, *requests]):
        raise ValueError("unknown result or counter ID")
    if any(identifier not in results for identifier in requests):
        raise ValueError("actual request counters lack terminal result")
    if not _integer(state.get("requests")) or not _integer(state.get("bytes")):
        raise ValueError("invalid batch counters")
    if state["requests"] > 8000 or state.get("stopReason") not in (
        None,
        "batch_request_budget_exceeded",
        "batch_bytes_budget_exceeded",
        "batch_duration_exceeded",
    ):
        raise ValueError("invalid batch terminal budget")
    if (
        any(not _integer(value) for value in requests.values())
        or sum(requests.values()) != state["requests"]
    ):
        raise ValueError("request counters disagree")
    started = state.get("startedAt")
    if (
        isinstance(started, bool)
        or not isinstance(started, (int, float))
        or not math.isfinite(started)
        or not 0 < started <= time.time() + 300
    ):
        raise ValueError("invalid batch time")
    code = state.get("codeSha256")
    if (
        not isinstance(code, dict)
        or not code
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
            for value in code.values()
        )
    ):
        raise ValueError("invalid code fingerprints")
    policy = state.get("samplingPolicy", {"sampleReviewEntryIds": []})
    opted = policy.get("sampleReviewEntryIds") if isinstance(policy, dict) else None
    groups = {row["entry_id"]: row["group"] for row in manifest}
    if (
        not isinstance(opted, list)
        or any(
            not isinstance(identifier, str) or groups.get(identifier) != "review"
            for identifier in opted
        )
        or len(set(opted)) != len(opted)
    ):
        raise ValueError("invalid review sampling policy")
    if "samplingPolicySha256" in state and state["samplingPolicySha256"] != _sha(
        _json(policy).encode()
    ):
        raise ValueError("invalid sampling fingerprint")
    for identifier, row in results.items():
        if not isinstance(row, dict):
            raise ValueError("invalid terminal result")  # noqa: TRY004 - all invalid ledger schema is rejected as ValueError.
        count = row.get("requests")
        if (
            row.get("entryId") != identifier
            or not isinstance(row.get("status"), str)
            or row.get("status") not in TERMINAL
            or not isinstance(row.get("reason"), str)
        ):
            raise ValueError("invalid or nonterminal result")
        if (
            not _integer(count)
            or count != requests.get(identifier, 0)
            or not isinstance(row.get("independentlyTested"), bool)
        ):
            raise ValueError("invalid result request accounting")
        if row["status"] == "inherited_block" and (
            count != 0 or row["independentlyTested"]
        ):
            raise ValueError("inherited stop is not an independent request")
        if count and not row["independentlyTested"]:
            raise ValueError("actual requests lack independent testing attribution")
        maximum = (
            3 if groups[identifier] == "review" and identifier not in opted else 12
        )
        if count > maximum:
            raise ValueError("row exceeded physical request limit")
        expected_scope = (
            "main_detail_samples"
            if groups[identifier] == "main"
            else "review_detail_samples"
            if identifier in opted
            else "list_diagnostic_only"
        )
        if row.get("samplingScope", expected_scope) != expected_scope:
            raise ValueError("result sampling scope disagrees with persisted policy")
        if row["status"] in {"sample_readable", "candidate_list"} and (
            not count or not row["independentlyTested"]
        ):
            raise ValueError(
                "readability requires actual independently tested requests"
            )
    return state, {
        "batch": path.parent.name,
        "path": str(path.resolve()),
        "ledgerSha256": _sha(raw),
        "codeSha256": code,
        "startedAt": started,
        "requests": state["requests"],
        "bytes": state["bytes"],
        "stopReason": state.get("stopReason"),
        "samplingPolicy": state.get("samplingPolicy", {"sampleReviewEntryIds": []}),
    }


def _write(path, text):
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _csv(value):
    text = str(value)
    return (
        "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else text
    )


def merge_ledgers(baseline, overlays, output):
    batches = [_read(path) for path in [baseline, *overlays]]
    initial = batches[0][0]
    for state, _ in batches[1:]:
        if (
            state["fingerprint"] != initial["fingerprint"]
            or state["manifest"] != initial["manifest"]
        ):
            raise ValueError("overlay manifest fingerprint differs")
    if any(
        later[1]["startedAt"] < earlier[1]["startedAt"]
        for earlier, later in pairwise(batches)
    ):
        raise ValueError("overlay batch times must preserve execution order")
    identities = [evidence["ledgerSha256"] for _, evidence in batches]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate evidence batch")
    output = Path(output).absolute()
    if any(part.is_symlink() for part in (output, *output.parents)):
        raise ValueError("symlink output is forbidden")
    output = output.resolve()
    repository = Path(__file__).resolve().parents[2]
    if output == repository or repository in output.parents or output.exists():
        raise ValueError("output must be new and outside repository")
    rows = []
    statuses, groups, gaps = {}, {}, []
    for entry in initial["manifest"]:
        identifier = entry["entry_id"]
        history = []
        for state, evidence in batches:
            if identifier not in state["results"]:
                continue
            result = state["results"][identifier]
            scope = result.get("samplingScope") or (
                "list_diagnostic_only"
                if entry["group"] == "review"
                else "main_detail_samples"
            )
            history.append(
                {
                    "status": result["status"],
                    "reason": result["reason"],
                    "requests": result["requests"],
                    "independentlyTested": result["independentlyTested"],
                    "samplingScope": scope,
                    "evidence": evidence,
                }
            )
        first = (
            history[0]
            if identifier in initial["results"]
            else {"status": "not_executed"}
        )
        latest = (
            history[-1]
            if history
            else {
                "status": "not_executed",
                "reason": "no_actual_result",
                "requests": 0,
                "independentlyTested": False,
                "samplingScope": "not_executed",
                "evidence": None,
            }
        )
        rows.append(
            {
                **entry,
                "baselineStatus": first["status"],
                "latestStatus": latest["status"],
                "reason": latest["reason"],
                "requests": latest["requests"],
                "evidence": {
                    **(latest["evidence"] or {}),
                    "samplingScope": latest["samplingScope"],
                    "independentlyTested": latest["independentlyTested"],
                },
                "history": history,
            }
        )
        statuses[latest["status"]] = statuses.get(latest["status"], 0) + 1
        group = groups.setdefault(
            entry["group"],
            {
                "inputCount": 0,
                "statuses": {},
                "latestAttributedRequests": 0,
                "latestIndependentlyTestedCount": 0,
                "physicalRequestsAllBatches": 0,
            },
        )
        group["inputCount"] += 1
        group["statuses"][latest["status"]] = (
            group["statuses"].get(latest["status"], 0) + 1
        )
        group["latestAttributedRequests"] += latest["requests"]
        group["latestIndependentlyTestedCount"] += latest["independentlyTested"]
        group["physicalRequestsAllBatches"] += sum(
            state["rowRequests"].get(identifier, 0) for state, _ in batches
        )
        if len(history) > 1 and (
            first["status"] == "error" or "unexpected_error:" in history[0]["reason"]
        ):
            gaps.append(
                {
                    "entryId": identifier,
                    "baselineStatus": first["status"],
                    "latestStatus": latest["status"],
                    "independentlyRetested": latest["independentlyTested"],
                    "evidence": latest["evidence"],
                }
            )
    summary = {
        "inputCount": len(rows),
        "inputSha256": initial["fingerprint"],
        "statuses": statuses,
        "groups": groups,
        "overlaidEntryCount": sum(len(row["history"]) > 1 for row in rows),
        "physicalRequestsAllBatches": sum(
            evidence["requests"] for _, evidence in batches
        ),
        "physicalBytesAllBatches": sum(evidence["bytes"] for _, evidence in batches),
        "latestAttributedRequests": sum(row["requests"] for row in rows),
        "latestIndependentlyTestedCount": sum(
            row["evidence"]["independentlyTested"] for row in rows
        ),
        "revisitedPriorToolGaps": gaps,
        "batches": [evidence for _, evidence in batches],
        "mergerCodeSha256": {
            "catalog_merge.py": _sha(Path(__file__).read_bytes()),
            "merge-tender-catalog.py": _sha(
                Path(__file__)
                .parents[1]
                .joinpath("merge-tender-catalog.py")
                .read_bytes()
            ),
        },
        "scope": "ordered local evidence overlays; no new requests, no source ledgers rewritten",
    }
    output.mkdir(mode=0o700)
    _write(output / "rows.jsonl", "".join(_json(row) + "\n" for row in rows))
    _write(output / "summary.json", _json(summary) + "\n")
    stream = io.StringIO(newline="")
    fields = [
        "entry_id",
        "group",
        "row_number",
        "entry_url",
        "name",
        "baselineStatus",
        "latestStatus",
        "reason",
        "requests",
        "evidenceBatch",
        "evidencePath",
        "ledgerSha256",
        "samplingScope",
        "independentlyTested",
    ]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        values = {key: row.get(key, "") for key in fields}
        values.update(
            evidenceBatch=row["evidence"].get("batch", ""),
            evidencePath=row["evidence"].get("path", ""),
            ledgerSha256=row["evidence"].get("ledgerSha256", ""),
            samplingScope=row["evidence"]["samplingScope"],
            independentlyTested=row["evidence"]["independentlyTested"],
        )
        writer.writerow({key: _csv(value) for key, value in values.items()})
    _write(output / "matrix.csv", stream.getvalue())
    return summary


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--overlay", action="append", type=Path, default=[])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    summary = merge_ledgers(args.baseline, args.overlay, args.output)
    aggregate = {
        key: value
        for key, value in summary.items()
        if key not in {"revisitedPriorToolGaps", "batches"}
    }
    aggregate["output"] = str(args.output.resolve())
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
