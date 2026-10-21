"""Real-source test driver. No database, account, scheduler or delivery imports."""

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import UnicodeDammit
from extrio.source_network import FetchBudget, SourceNetwork, SourceNetworkError

from .adapters import PROFILES, agency_resource, canonical_url, parse_agency_data, parse_detail, parse_list, sample_records, validate_detail


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class TestNetwork(SourceNetwork):
    __test__ = False

    def __init__(self, hosts, *, transport=None):
        super().__init__(
            set(hosts),
            allow_http=True,
            max_attempts=1,
            max_redirects=2,
            request_timeout=15,
            max_concurrency=1,
            requests_per_second=0.5,
            transport=transport,
            budget=FetchBudget(max_seconds=600, max_page_bytes=5_000_000, max_total_bytes=80_000_000),
        )
        self.trace = []
        self.attempts = 0

    async def _request_once(self, url, pinned_url, host_header, tls_name, **kwargs):
        if self.attempts >= 240:
            raise SourceNetworkError("test_request_cap")
        self.attempts += 1
        try:
            response = await super()._request_once(url, pinned_url, host_header, tls_name, **kwargs)
        except Exception as exc:
            self.trace.append({"url": url, "errorType": type(exc).__name__})
            raise
        self.trace.append(
            {
                "url": url,
                "status": response.status,
                "bytes": len(response.body),
                "sha256": digest(response.body),
                "contentType": response.headers.get("content-type"),
                "location": response.headers.get("location"),
            }
        )
        if urlsplit(url).path == "/robots.txt" and response.status == 200:
            if b"<html" in response.body[:2000].lower() or b"<!doctype html" in response.body[:2000].lower():
                raise SourceNetworkError("robots_returned_html_unverified")
        return response


class Sampler:
    def __init__(self, sid, pdf_python=None, ocr_command=None, pdftoppm=None):
        self.sid = sid
        self.profile = PROFILES[sid]
        self.network = TestNetwork(self.profile.hosts)
        self.cache = {}
        self.pdf_python = pdf_python
        self.pdf_count = 0
        self.ocr_command = ocr_command
        self.pdftoppm = pdftoppm

    async def fetch(self, url):
        url = canonical_url(url, self.profile)
        if url not in self.cache:
            try:
                response = (await self.network.fetch(url, respect_robots=True)).require_success()
            except SourceNetworkError as exc:
                if str(exc) != "redirect_https_downgrade" or self.sid != "fudan":
                    raise
                last = self.network.trace[-1]
                target = urlsplit(urljoin(last["url"], last.get("location") or ""))
                if (
                    target.scheme != "http"
                    or target.hostname != "www.ccgp.gov.cn"
                    or target.port not in {None, 80}
                    or target.username
                    or target.password
                    or not target.path.startswith("/cggg/")
                ):
                    raise
                # Never request the downgraded URL. Try its exact HTTPS counterpart.
                secure = urlunsplit(("https", "www.ccgp.gov.cn", target.path, target.query, ""))
                response = (await self.network.fetch(secure, respect_robots=True)).require_success()
            prefix = response.body[:8000].lower()
            if b"<title>" in prefix and any(marker in prefix for marker in [b"<title>access denied", b"<title>captcha"]):
                raise SourceNetworkError("access_challenge")
            self.cache[url] = response
        return self.cache[url]

    async def html(self, url):
        response = await self.fetch(url)
        text = UnicodeDammit(response.body).unicode_markup or response.body.decode("utf-8", errors="replace")
        return response.url, text

    async def pdf(self, url):
        if not self.pdf_python:
            raise ValueError("pdf_python_not_configured")
        if self.pdf_count >= 10:
            raise ValueError("source_pdf_cap")
        response = await self.fetch(url)
        self.pdf_count += 1
        if not response.body.startswith(b"%PDF-"):
            raise ValueError("pdf_magic_mismatch")
        env = {**os.environ, "TENDER_OCR_COMMAND": self.ocr_command or "", "TENDER_PDFTOPPM": self.pdftoppm or ""}
        proc = await asyncio.create_subprocess_exec(
            self.pdf_python,
            str(Path(__file__).with_name("pdf_text.py")),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(response.body), 80)
        except (TimeoutError, asyncio.CancelledError):
            proc.kill()
            await proc.wait()
            raise
        if proc.returncode:
            raise ValueError("pdf_parser_failed:" + stderr.decode(errors="replace").strip().splitlines()[-1][:200])
        return json.loads(stdout)

    async def detail(self, record):
        url, html = await self.html(record["detailUrl"])
        detail = parse_detail(self.sid, html, url)
        lineage = [{"role": "discovered_detail", "url": url, "sha256": digest(html)}]
        if detail.frame_url:
            frame_url, frame_html = await self.html(detail.frame_url)
            lineage.append({"role": "public_iframe", "url": frame_url, "sha256": digest(frame_html)})
            detail = await self.agency_detail(frame_url, frame_html, record, lineage)
        # Resolve only the exact public CCGP link emitted by the publisher, never a search guess.
        if detail.mode == "original_pointer" and len(set(detail.original_urls)) == 1:
            original_url, original_html = await self.html(detail.original_urls[0])
            original = parse_detail("ccgp", original_html, original_url)
            detail.original_title = original.title
            lineage.append(
                {
                    "role": "publisher_linked_original",
                    "url": original_url,
                    "sha256": digest(original_html),
                    "title": original.title,
                    "publishedAt": original.published_at,
                }
            )
            if validate_detail(detail, record) == "original_not_resolved" and original.title and original.content and original.published_at:
                detail.content = original.content
                detail.mode = "publisher_linked_original"
                detail.attachments = original.attachments
                detail.fields["originalFields"] = original.fields
                detail.fields["originalTitleRequiresReview"] = not self.original_title_matches(detail.title, original)
        for pdf_url in detail.pdf_urls[:2]:
            extracted = await self.pdf(pdf_url)
            lineage.append(
                {
                    "role": "embedded_body_pdf",
                    "url": pdf_url,
                    "pages": extracted["pages"],
                    "textSha256": digest(extracted["text"]),
                    "extraction": extracted["extraction"],
                }
            )
            detail.content = "\n".join(v for v in [detail.content, extracted["text"]] if v)
            detail.mode = "embedded_pdf_ocr" if extracted["reviewRequired"] else "embedded_pdf_text"
            if extracted["reviewRequired"]:
                detail.fields["ocrReviewRequired"] = True
                detail.fields["minimumOcrLineConfidence"] = extracted["minimumLineConfidence"]
        reason = validate_detail(detail, record, source_id=self.sid)
        if not reason and detail.fields.get("originalTitleRequiresReview"):
            reason = "linked_original_identity_review"
        if not reason and detail.fields.get("ocrReviewRequired"):
            reason = "ocr_manual_review_required"
        return detail, lineage, reason

    @staticmethod
    def original_title_matches(title, original):
        from extrio.harvest import titles_consistent

        if titles_consistent(title, original.title):
            return True
        # A publisher's short "procurement information" title and the linked
        # statutory notice differ only in the explicitly recognized notice suffix.
        if title.endswith("采购信息"):
            stem = title.removesuffix("采购信息")
            if any(titles_consistent(stem + suffix, original.title) for suffix in ("公开招标公告", "采购项目公开招标公告")):
                return True
        stem = re.sub(r"(?:采购信息|采购更正信息|更正信息)(?:[（(]第[一二三四五六七八九十0-9]+次[）)])?$", "", title)
        expected_stage = "correction" if "更正信息" in title else "procurement"
        return (
            stem != title
            and original.fields.get("noticeStage") == expected_stage
            and original.fields.get("buyer") == "厦门大学"
            and titles_consistent(stem, original.fields.get("projectName", ""))
        )

    async def agency_detail(self, frame_url, frame_html, record, lineage):
        resource_url, guid = agency_resource(frame_url, frame_html)
        if parse_qs(urlsplit(record["detailUrl"]).query).get("guid") != [guid]:
            raise ValueError("list_and_frame_guid_mismatch")
        resource_url, raw = await self.html(resource_url)
        lineage.append({"role": "public_template_data", "url": resource_url, "sha256": digest(raw)})
        return parse_agency_data(json.loads(raw), record, guid, result="jieGuo_view.html" in frame_url)


STOP_ERRORS = {
    "authentication_or_access_required",
    "http_status_429",
    "robots_disallowed",
    "robots_returned_html_unverified",
    "access_challenge",
    "test_request_cap",
    "duration_exceeded",
    "total_bytes_exceeded",
}


async def run_source(sid, args):
    sampler = Sampler(sid, args.pdf_python, args.ocr_command, args.pdftoppm)
    profile = sampler.profile
    report = {
        "sourceId": sid,
        "name": profile.name,
        "entryUrl": profile.entry,
        "startedAt": datetime.now(UTC).isoformat(),
        "listPages": [],
        "samples": [],
        "skipped": [],
        "errors": [],
    }
    pages, seen, next_url = [], set(), profile.entry
    try:
        retry_path = getattr(args, "retry_from", None)
        retry_records = []
        if retry_path:
            previous = json.loads(retry_path.read_text())
            if previous["sourceId"] != sid:
                raise ValueError("retry_source_mismatch")
            report["retryOf"] = str(retry_path)
            retry_records = [
                {
                    "detailUrl": s["discoveredUrl"],
                    "listPageUrl": s["listPageUrl"],
                    "listTitle": s["listTitle"],
                    "listPublishedAt": s["listPublishedAt"],
                }
                for s in previous["samples"]
                if s["decision"] == "failed"
            ][: args.details]
        for _ in range(0 if retry_path else args.pages):
            if not next_url or next_url in seen:
                break
            seen.add(next_url)
            final_url, html = await sampler.html(next_url)
            page = parse_list(sid, html, final_url)
            records = []
            for record in page.records:
                try:
                    record = {**record, "detailUrl": canonical_url(record["detailUrl"], profile), "listPageUrl": next_url}
                    if record["detailUrl"] == profile.entry or urlsplit(record["detailUrl"]).path.rsplit("/", 1)[-1].startswith("index"):
                        raise ValueError("list_link_not_detail")
                    records.append(record)
                except ValueError as exc:
                    report["skipped"].append({"url": record.get("detailUrl"), "reason": str(exc)})
            old = {r["detailUrl"] for rows in pages for r in rows}
            new = len({r["detailUrl"] for r in records} - old)
            report["listPages"].append(
                {
                    "url": next_url,
                    "finalUrl": final_url,
                    "records": len(page.records),
                    "newDetailUrls": new,
                    "sha256": digest(html),
                    "nextUrl": page.next_url,
                }
            )
            if not records:
                raise ValueError("empty_or_changed_list_structure")
            pages.append(records)
            if not new:
                report["errors"].append({"stage": "pagination", "reason": "repeated_page_without_new_urls"})
                break
            next_url = page.next_url
        selected = retry_records if retry_path else sample_records(pages, args.details)
        report["discoveredRecords"] = list({r["detailUrl"]: r for page in pages for r in page}.values())
        report["selectedDetails"] = len(selected)
        for record in selected:
            sample = {
                "sourceId": sid,
                "discoveredUrl": record["detailUrl"],
                "listPageUrl": record["listPageUrl"],
                "listTitle": record.get("listTitle"),
                "listPublishedAt": record.get("listPublishedAt"),
            }
            try:
                detail, lineage, reason = await sampler.detail(record)
                sample.update(
                    title=detail.title,
                    publishedAt=detail.published_at,
                    contentMode=detail.mode,
                    decision="rejected" if reason else "accepted",
                    reason=reason,
                    contentCharacters=len(detail.content),
                    contentSha256=digest(detail.content),
                    lineage=lineage,
                    attachmentUrls=detail.attachments,
                    fields=detail.fields,
                    originalTitle=detail.original_title,
                    entityKey=digest(record["detailUrl"])[:24],
                )
                if args.content_dir:
                    with (args.content_dir / f"{sid}.jsonl").open("a") as handle:
                        handle.write(json.dumps({**sample, "content": detail.content}, ensure_ascii=False) + "\n")
            except (ValueError, SourceNetworkError, TimeoutError) as exc:
                sample.update(decision="failed", reason=str(exc), errorType=type(exc).__name__)
                if str(exc) in STOP_ERRORS:
                    report["samples"].append(sample)
                    raise
            report["samples"].append(sample)
            print(
                json.dumps(
                    {
                        "sourceId": sid,
                        "completed": len(report["samples"]),
                        "decision": sample["decision"],
                        "reason": sample.get("reason"),
                        "mode": sample.get("contentMode"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    except (ValueError, SourceNetworkError, TimeoutError) as exc:
        report["errors"].append({"stage": "source", "reason": str(exc), "errorType": type(exc).__name__})
    report.update(
        trace=sampler.network.trace,
        requests=sampler.network.attempts,
        bytes=sampler.network.budget.total_bytes,
        pdfDownloads=sampler.pdf_count,
        endedAt=datetime.now(UTC).isoformat(),
    )
    report["summary"] = {
        "listPages": len(report["listPages"]),
        "discoveredUniqueDetails": len({r["detailUrl"] for p in pages for r in p}),
        "selected": report.get("selectedDetails", 0),
        "attempted": len(report["samples"]),
        "accepted": sum(s["decision"] == "accepted" for s in report["samples"]),
        "rejected": sum(s["decision"] == "rejected" for s in report["samples"]),
        "failed": sum(s["decision"] == "failed" for s in report["samples"]),
        "unattemptedDiscoveredDetails": max(0, len(report.get("discoveredRecords", [])) - len(report["samples"])),
    }
    write_json(args.output / f"{sid}.json", report)
    print(json.dumps({"sourceId": sid, **report["summary"]}, ensure_ascii=False), flush=True)
    return report


async def main(args):
    reports = []
    for sid in args.sources:
        reports.append(await run_source(sid, args))
    summary = {
        "recordedAt": datetime.now(UTC).isoformat(),
        "sourceCount": len(reports),
        "limits": {"listPagesPerSource": args.pages, "detailsPerSource": args.details, "rps": 0.5},
        "totals": {k: sum(r["summary"][k] for r in reports) for k in reports[0]["summary"]},
        "businessDatabaseWrites": 0,
        "paidModelCalls": 0,
        "productionSchedulingEnabled": False,
        "commercialAuthorizationVerified": False,
        "fullContentDirectory": str(args.content_dir) if args.content_dir else None,
        "sources": [{"sourceId": r["sourceId"], "name": r["name"], **r["summary"]} for r in reports],
    }
    write_json(args.output / "summary.json", summary)
    with (args.output / "samples.jsonl").open("w") as handle:
        for report in reports:
            for sample in report["samples"]:
                handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="+", choices=list(PROFILES), default=list(PROFILES))
    parser.add_argument("--pages", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--details", type=int, choices=range(1, 101), default=20)
    parser.add_argument(
        "--all-discovered", action="store_true", help="Process all discovered URLs within 3 list pages, hard cap 100/source"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--content-dir", type=Path)
    parser.add_argument("--pdf-python", help="Python executable with pypdf; no automatic installation")
    parser.add_argument("--ocr-command", help="Optional local OCR binary; OCR results always require manual review")
    parser.add_argument("--pdftoppm", help="Optional Poppler renderer used only for image-only PDF body pages")
    parser.add_argument("--retry-from", type=Path, help="Retry only failed detail samples from one saved source result")
    args = parser.parse_args()
    if args.all_discovered:
        args.details = 100
    if args.retry_from and len(args.sources) != 1:
        parser.error("retry_requires_one_explicit_source")
    if args.content_dir:
        repo = Path(__file__).resolve().parents[2]
        if args.content_dir.resolve().is_relative_to(repo):
            parser.error("full_content_must_remain_outside_repository")
    args.output.mkdir(parents=True, exist_ok=False)
    if args.content_dir:
        args.content_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
