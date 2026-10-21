"""Verify explicit source attempts and assemble a metadata-only acceptance bundle."""

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .adapters import PROFILES, Detail, notice_stage_from_url
from .run import Sampler, digest, write_json


def load(path):
    return json.loads(path.read_text())


def records_for(path):
    folder = Path(load(path.parent / "summary.json")["fullContentDirectory"])
    return {row["discoveredUrl"]: row for row in map(json.loads, (folder / f"{load(path)['sourceId']}.jsonl").read_text().splitlines())}


def assemble(paths: list[Path], retries: list[Path], output: Path, content_dir: Path):
    repo = Path(__file__).resolve().parents[2]
    if content_dir.resolve().is_relative_to(repo):
        raise ValueError("full_content_must_remain_outside_repository")
    sources, full_records = {}, {}
    for path in paths:
        report = load(path)
        sid = report["sourceId"]
        if sid in sources:
            raise ValueError("duplicate_base_source")
        sources[sid] = {**report, "baseResult": str(path), "retryResults": []}
        full_records[sid] = records_for(path)
    for path in retries:
        retry = load(path)
        sid = retry["sourceId"]
        report = sources[sid]
        old = {sample["discoveredUrl"]: sample for sample in report["samples"]}
        for sample in retry["samples"]:
            if sample["discoveredUrl"] not in old or old[sample["discoveredUrl"]]["decision"] != "failed":
                raise ValueError("retry_must_replace_a_previously_failed_sample")
            old[sample["discoveredUrl"]] = {**sample, "previousAttemptReason": old[sample["discoveredUrl"]]["reason"]}
        report["samples"] = list(old.values())
        report["retryResults"].append(str(path))
        full_records[sid].update(records_for(path))
    if set(sources) != set(PROFILES):
        raise ValueError("acceptance_requires_all_six_profiles")
    samples, private_rows, statuses = [], [], []
    for sid, report in sources.items():
        urls = [s["discoveredUrl"] for s in report["samples"]]
        if len(urls) != len(set(urls)):
            raise ValueError("duplicate_sample_url")
        modes = Counter()
        for sample in report["samples"]:
            if sample["decision"] != "failed":
                full = full_records[sid][sample["discoveredUrl"]]
                if digest(full["content"]) != sample["contentSha256"]:
                    raise ValueError("body_evidence_hash_mismatch")
                if "content" in sample:
                    raise ValueError("full_body_in_repository_metadata")
                if sample["decision"] == "accepted" and sample["contentMode"] == "publisher_linked_original":
                    fields = dict(sample["fields"]["originalFields"])
                    original_url = next(row["url"] for row in sample["lineage"] if row["role"] == "publisher_linked_original")
                    fields["noticeStage"] = notice_stage_from_url(original_url)
                    original = Detail(title=sample["originalTitle"], fields=fields)
                    if not Sampler.original_title_matches(sample["title"], original):
                        raise ValueError("linked_original_failed_final_stage_identity_check")
                private_rows.append({**sample, "content": full["content"]})
                modes[sample["contentMode"]] += 1
            samples.append(sample)
        counts = Counter(s["decision"] for s in report["samples"])
        status = {
            "sourceId": sid,
            "name": report["name"],
            "listPages": len(report["listPages"]),
            "discoveredUniqueDetails": report["summary"]["discoveredUniqueDetails"],
            "attempted": len(report["samples"]),
            "accepted": counts["accepted"],
            "reviewRequired": counts["rejected"],
            "failed": counts["failed"],
            "unattemptedDiscoveredDetails": max(0, report["summary"]["discoveredUniqueDetails"] - len(report["samples"])),
            "skippedListLinks": len(report.get("skipped", [])),
            "parsedContentModes": dict(modes),
            "baseResult": report["baseResult"],
            "retryResults": report["retryResults"],
        }
        statuses.append(status)
    all_rounds = sorted({p.parent for p in paths + retries})
    round_reports = [load(p) for folder in all_rounds for p in folder.glob("*.json") if p.name != "summary.json" and "sourceId" in load(p)]
    summary = {
        "recordedAt": datetime.now(UTC).isoformat(),
        "sourceCount": len(statuses),
        "listPages": sum(s["listPages"] for s in statuses),
        "discoveredUniqueDetailsWithinSources": sum(s["discoveredUniqueDetails"] for s in statuses),
        "detailSamples": len(samples),
        "parsedSamples": len(private_rows),
        "accepted": sum(s["accepted"] for s in statuses),
        "reviewRequired": sum(s["reviewRequired"] for s in statuses),
        "failed": sum(s["failed"] for s in statuses),
        "parsedContentModes": dict(Counter(s.get("contentMode") for s in samples)),
        "reviewReasons": dict(Counter(s["reason"] for s in samples if s["decision"] != "accepted")),
        "recordedNetworkAttemptsAcrossSelectedRounds": sum(r["requests"] for r in round_reports),
        "recordedDetailAttemptsAcrossSelectedRounds": sum(len(r["samples"]) for r in round_reports),
        "unattemptedDiscoveredDetails": sum(s["unattemptedDiscoveredDetails"] for s in statuses),
        "skippedListLinks": sum(s["skippedListLinks"] for s in statuses),
        "fullContentFile": str(content_dir / "records.jsonl"),
        "businessDatabaseWrites": 0,
        "paidModelCalls": 0,
        "productionSchedulingEnabled": False,
        "commercialAuthorizationVerified": False,
        "sources": statuses,
    }
    output.mkdir(parents=True, exist_ok=False)
    content_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_json(output / "summary.json", summary)
    with (output / "samples.jsonl").open("w") as handle:
        handle.writelines(json.dumps(s, ensure_ascii=False) + "\n" for s in samples)
    with (content_dir / "records.jsonl").open("w") as handle:
        handle.writelines(json.dumps(s, ensure_ascii=False) + "\n" for s in private_rows)
    counts_by_source = {s["sourceId"]: s for s in statuses}
    profiles = {
        sid: {
            **asdict(p),
            "hosts": sorted(p.hosts),
            "publishedGatherSpec": False,
            "anonymousListObserved": counts_by_source[sid]["listPages"] > 0,
            "parsedAnonymousDetailSamples": sum(counts_by_source[sid]["parsedContentModes"].values()),
            "ordinaryAttachmentAccess": "unverified_not_requested",
            "businessLoginRequired": "unverified_not_requested",
            "commercialAuthorization": "unverified",
        }
        for sid, p in PROFILES.items()
    }
    write_json(output / "adapter-profiles.json", profiles)
    code_files = [
        *Path(__file__).parent.glob("*.py"),
        Path(__file__).with_name("vision_ocr.swift"),
        repo / "scripts/test-tender-sources.py",
    ]
    write_json(
        output / "verification.json",
        {
            "bodyHashesVerified": len(private_rows),
            "duplicateSampleUrls": 0,
            "fullBodiesInRepository": 0,
            "finalLinkedOriginalStageGate": "passed",
            "codeSha256": {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files},
        },
    )
    return summary


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", nargs="+", type=Path, required=True)
    parser.add_argument("--retries", nargs="*", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--content-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(assemble(args.results, args.retries, args.output, args.content_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
