"""Opt-in, bounded catalog diagnostics. No business application or database imports."""

import argparse
import asyncio
import csv
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import re
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup, UnicodeDammit
from extrio.public_pagination import public_list_response_issue
from extrio.source_network import SourceNetwork, SourceNetworkError

from .catalog import (
    historical_restriction,
    inspect_detail,
    inspect_list,
    load_catalog,
    validate_entry,
)


@dataclass(frozen=True)
class RunLimits:
    max_requests: int = 8000
    max_bytes: int = 1_000_000_000
    max_seconds: float = 5400
    row_seconds: float = 60
    page_bytes: int = 2_000_000
    main_requests: int = 12
    review_requests: int = 3
    spacing: float = 2
    concurrency: int = 4


def _hash(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else value.encode()
    ).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _csv_value(value):
    text = str(value)
    return (
        "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value
    )


def _atomic(path, value):
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value if isinstance(value, bytes) else value.encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _output(path, resume):
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(
            "symlink output paths are forbidden; use a canonical absolute path"
        )
    path = path.resolve()
    repository = Path(__file__).resolve().parents[2]
    if path == repository or repository in path.parents:
        raise ValueError("output must be outside the repository")
    if path.exists():
        if not resume:
            raise ValueError("output already exists; --resume is required")
        if not path.is_dir() or path.stat().st_mode & 0o077:
            raise ValueError("resume output must be a private 0700 directory")
        if any(
            item.is_symlink() or (item.is_file() and item.stat().st_mode & 0o077)
            for item in path.rglob("*")
        ):
            raise ValueError("resume output has unsafe permissions or symlinks")
    else:
        if resume:
            raise ValueError("resume output does not exist")
        path.mkdir(mode=0o700)
    return path


def _host(url):
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def _challenge(body, url):
    text = UnicodeDammit(body).unicode_markup or body.decode("utf-8", errors="replace")
    if public_list_response_issue(url, text):
        return True
    soup = BeautifulSoup(text, "html.parser")
    for node in soup.select(
        'script, style, noscript, template, [hidden], [aria-hidden="true"]'
    ):
        node.decompose()
    for node in reversed(soup.select("[style]")):
        if re.search(
            r"display\s*:\s*none|visibility\s*:\s*hidden",
            node.get("style", ""),
            re.IGNORECASE,
        ):
            node.decompose()
    compact = re.sub(r"\s+", "", soup.get_text(" ", strip=True)).lower()
    title = (
        re.sub(r"\s+", "", soup.title.get_text(strip=True)).lower()
        if soup.title
        else ""
    )
    markers = (
        "访问过于频繁",
        "访问太频繁",
        "请求过于频繁",
        "访问频率过高",
        "请输入验证码",
        "人机验证",
        "安全验证",
        "访问受限",
        "拒绝访问",
        "您没有权限",
        "accessdenied",
        "toomanyrequests",
        "verifyyouarehuman",
        "checkingyourbrowser",
        "captcha",
        "justamoment",
    )
    if any(marker in title for marker in markers):
        return True
    dated_notice = bool(re.search(r"20\d{2}[-年/.]\d{1,2}", compact)) and any(
        re.search(r"采购|招标|中标|成交|公告", anchor.get_text())
        for anchor in soup.select("a[href]")
    )
    return (
        len(compact) < 800
        and not dated_notice
        and any(marker in compact for marker in markers)
    )


class _ByteBudget:
    def __init__(self, network):
        self.network = network
        self.max_page_bytes = network.runner.limits.page_bytes
        self.max_total_bytes = network.runner.limits.max_bytes
        self.max_seconds = network.runner.limits.max_seconds
        self.max_requests = None

    @property
    def total_bytes(self):
        return self.network.runner.state["bytes"]

    @total_bytes.setter
    def total_bytes(self, value):
        runner = self.network.runner
        difference = value - runner.state["bytes"]
        runner.state["bytes"] = value
        if self.network.active_trace is not None:
            self.network.active_trace["bytes"] += difference
        runner.persist()


class CatalogNetwork(SourceNetwork):
    def __init__(self, runner, host):
        super().__init__(
            {host},
            transport=runner.transport,
            max_attempts=1,
            max_redirects=2,
            request_timeout=15,
            max_concurrency=1,
        )
        self.runner = runner
        self.host = host
        self.row = None
        self.active_trace = None
        self.in_robots = False
        self.budget = _ByteBudget(self)
        for origin, lines in runner.state["robots"].items():
            if _host(origin) == host:
                parser = RobotFileParser()
                parser.parse(lines)
                self.robots[origin] = parser

    async def target(self, url):
        invalid = validate_entry(replace(self.row, entry_url=url))
        if invalid:
            raise SourceNetworkError(invalid)
        return await super().target(url)

    async def _request_once(self, url, pinned_url, host_header, tls_name, **kwargs):
        runner = self.runner
        host_state = runner.state["hosts"][self.host]
        if host_state["blocked"]:
            raise SourceNetworkError("host_blocked:" + host_state["blocked"])
        runner.check_budget()
        row = self.row
        maximum = (
            runner.limits.review_requests
            if row.group == "review"
            and row.entry_id not in runner.sample_review_entry_ids
            else runner.limits.main_requests
        )
        if runner.state["rowRequests"].get(row.entry_id, 0) >= maximum:
            raise SourceNetworkError("row_request_budget_exceeded")
        await asyncio.sleep(
            max(0, host_state["lastRequestAt"] + runner.limits.spacing - time.time())
        )
        runner.check_budget()
        runner.state["requests"] += 1
        runner.state["rowRequests"][row.entry_id] = (
            runner.state["rowRequests"].get(row.entry_id, 0) + 1
        )
        host_state["lastRequestAt"] = time.time()
        trace = {
            "id": runner.state["requests"],
            "entryId": row.entry_id,
            "url": url,
            "startedAt": time.time(),
            "bytes": 0,
            "outcome": "in_flight",
        }
        self.active_trace = trace
        runner.write_trace(trace)
        runner.persist()
        try:
            response = await super()._request_once(
                url, pinned_url, host_header, tls_name, **kwargs
            )
            trace.update(
                status=response.status,
                sha256=_hash(response.body),
                contentType=response.headers.get("content-type"),
                location=response.headers.get("location"),
            )
            trace["sample"] = f"samples/request-{trace['id']:05d}.body"
            _atomic(runner.output / trace["sample"], response.body)
            if response.status in {401, 403, 429}:
                reason = (
                    "source_rate_limited"
                    if response.status == 429
                    else "authentication_or_access_required"
                )
                host_state["blocked"] = reason
                raise SourceNetworkError(reason)
            if self.in_robots or urlsplit(url).path == "/robots.txt":
                if response.status == 200 and (
                    "html" in response.headers.get("content-type", "").lower()
                    or re.search(
                        rb"<!doctype\s|</?[a-z][^>]*>", response.body, re.IGNORECASE
                    )
                ):
                    host_state["blocked"] = "robots_returned_html_unverified"
                    raise SourceNetworkError("robots_returned_html_unverified")
                if response.status in {200, 404, 410}:
                    origin = (
                        urlsplit(url)
                        ._replace(path="", query="", fragment="")
                        .geturl()
                        .rstrip("/")
                    )
                    runner.state["robots"][origin] = (
                        response.body.decode("utf-8", errors="replace").splitlines()
                        if response.status == 200
                        else []
                    )
            if _challenge(response.body, response.url):
                host_state["blocked"] = "access_challenge"
                raise SourceNetworkError("access_challenge")
            trace["outcome"] = "response"
            return response
        except asyncio.CancelledError:
            trace["outcome"] = "cancelled"
            raise
        except Exception as exc:
            trace["outcome"] = "error"
            trace["error"] = (
                str(exc) if isinstance(exc, SourceNetworkError) else type(exc).__name__
            )
            raise
        finally:
            trace["finishedAt"] = time.time()
            runner.write_trace(trace)
            runner.persist()
            self.active_trace = None

    async def check_robots(self, url, *, within_slot=False):
        self.in_robots = True
        try:
            await super().check_robots(url, within_slot=within_slot)
        finally:
            self.in_robots = False


class CatalogRunner:
    def __init__(
        self,
        entries,
        output,
        *,
        resume=False,
        transport=None,
        limits=None,
        sample_review_entry_ids=None,
    ):
        self._lock_fd = None
        self.entries = entries
        selected_review = (
            set(sample_review_entry_ids)
            if sample_review_entry_ids is not None
            else None
        )
        valid_review = {entry.entry_id for entry in entries if entry.group == "review"}
        if selected_review is not None and not selected_review <= valid_review:
            raise ValueError("sample review IDs must identify existing review entries")
        self.transport = transport
        self.limits = limits or RunLimits()
        values = asdict(self.limits)
        hard_limits = asdict(RunLimits())
        if (
            any(value <= 0 for key, value in values.items() if key != "spacing")
            or any(
                values[key] > maximum
                for key, maximum in hard_limits.items()
                if key != "spacing"
            )
            or self.limits.spacing < (0 if transport is not None else 2)
        ):
            raise ValueError("invalid limits")
        self.output = _output(Path(output), resume)
        descriptor = os.open(
            self.output / ".runner.lock",
            os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise ValueError("output is locked by another runner") from exc
        self._lock_fd = descriptor
        # Only the exclusive owner can discard an interrupted atomic replacement.
        for item in self.output.rglob("*.tmp"):
            item.unlink()
        fingerprint = _hash(_json([asdict(entry) for entry in entries]))
        code = {
            name: _hash(Path(__file__).with_name(name).read_bytes())
            for name in (
                "catalog.py",
                "catalog_run.py",
                "adapters.py",
                "catalog_template_university.py",
                "catalog_template_henan.py",
                "catalog_template_zjnu.py",
            )
        }
        for module in (
            "source_network",
            "public_pagination",
            "harvest",
            "pagination",
            "contracts",
            "integrity",
            "official_documents",
        ):
            code[f"extrio/{module}.py"] = _hash(
                Path(importlib.util.find_spec(f"extrio.{module}").origin).read_bytes()
            )
        if len({entry.entry_id for entry in entries}) != len(entries):
            raise ValueError("entry IDs must be unique")
        if resume:
            self.state = json.loads((self.output / "ledger.json").read_text())
            if self.state["fingerprint"] != fingerprint or self.state[
                "limits"
            ] != asdict(self.limits):
                raise ValueError(
                    "input or limits fingerprint differs from the persisted run"
                )
            if self.state["codeSha256"] != code:
                raise ValueError(
                    "code fingerprint differs from the persisted run; do not silently mix implementations"
                )
            saved_policy = self.state.get(
                "samplingPolicy", {"sampleReviewEntryIds": []}
            )
            policy_ids = saved_policy.get("sampleReviewEntryIds")
            if (
                not isinstance(policy_ids, list)
                or any(not isinstance(identifier, str) for identifier in policy_ids)
                or policy_ids != sorted(set(policy_ids))
                or not set(policy_ids) <= valid_review
                or self.state.get("samplingPolicySha256") != _hash(_json(saved_policy))
            ):
                raise ValueError("invalid saved sampling policy fingerprint")
            if (
                selected_review is not None
                and sorted(selected_review) != saved_policy["sampleReviewEntryIds"]
            ):
                raise ValueError(
                    "sampling policy fingerprint differs from persisted run"
                )
            self.state["samplingPolicy"] = saved_policy
            selected_review = set(saved_policy["sampleReviewEntryIds"])
            for identifier in self.state["running"]:
                self.state["results"][identifier] = {
                    "entryId": identifier,
                    "status": "interrupted",
                    "reason": "previous_process_interrupted",
                    "independentlyTested": True,
                }
                previous = next(
                    entry for entry in entries if entry.entry_id == identifier
                )
                self.state["hosts"].setdefault(
                    _host(previous.entry_url), {"lastRequestAt": 0}
                )["blocked"] = "previous_process_interrupted"
            self.state["running"] = []
        else:
            self.state = {
                "version": 1,
                "fingerprint": fingerprint,
                "limits": asdict(self.limits),
                "startedAt": time.time(),
                "requests": 0,
                "bytes": 0,
                "rowRequests": {},
                "results": {},
                "running": [],
                "hosts": {},
                "robots": {},
                "stopReason": None,
                "manifest": [asdict(entry) for entry in entries],
                "codeSha256": code,
                "samplingPolicy": {
                    "sampleReviewEntryIds": sorted(selected_review or set())
                },
                "samplingPolicySha256": _hash(
                    _json({"sampleReviewEntryIds": sorted(selected_review or set())})
                ),
            }
        self.sample_review_entry_ids = selected_review or set()
        self.networks = {}
        self.host_locks = {}
        self.slots = asyncio.Semaphore(min(4, self.limits.concurrency))
        for directory in ("samples", "traces", "rows"):
            (self.output / directory).mkdir(mode=0o700, exist_ok=True)
        self.persist()

    def close(self):
        if getattr(self, "_lock_fd", None) is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def __del__(self):
        self.close()

    def persist(self):
        _atomic(self.output / "ledger.json", _json(self.state) + "\n")

    def write_trace(self, trace):
        _atomic(
            self.output / "traces" / f"request-{trace['id']:05d}.json",
            _json(trace) + "\n",
        )

    def check_budget(self):
        reason = self.state["stopReason"]
        if not reason:
            if self.state["requests"] >= self.limits.max_requests:
                reason = "batch_request_budget_exceeded"
            elif self.state["bytes"] >= self.limits.max_bytes:
                reason = "batch_bytes_budget_exceeded"
            elif time.time() - self.state["startedAt"] >= self.limits.max_seconds:
                reason = "batch_duration_exceeded"
        if reason:
            self.state["stopReason"] = reason
            self.persist()
            raise SourceNetworkError(reason)

    async def fetch(self, network, url):
        response = (await network.fetch(url, respect_robots=True)).require_success()
        if (
            response.body.startswith(b"%PDF-")
            or "pdf" in response.headers.get("content-type", "").lower()
        ):
            raise SourceNetworkError("pdf_not_sampled")
        if response.status == 204:
            raise SourceNetworkError("empty_response")
        return response, UnicodeDammit(
            response.body
        ).unicode_markup or response.body.decode("utf-8", errors="replace")

    async def inspect(self, entry, network):
        response, html = await self.fetch(network, entry.entry_url)
        inspection = inspect_list(html, response.url)
        result = {
            "status": inspection.status,
            "reason": inspection.reason,
            "list": asdict(inspection),
            "details": [],
            "samplingScope": self.sampling_scope(entry),
        }
        if inspection.status == "restricted":
            self.state["hosts"][network.host]["blocked"] = inspection.reason
        if (
            entry.group == "review"
            and entry.entry_id not in self.sample_review_entry_ids
        ):
            return result
        allowed = 0
        cross_host = []
        for candidate in inspection.candidates:
            if allowed >= 2:
                break
            if _host(candidate.url) != network.host:
                cross_host.append(candidate.url)
                continue
            if validate_entry(replace(entry, entry_url=candidate.url)):
                continue
            if (
                urlsplit(response.url).scheme == "https"
                and urlsplit(candidate.url).scheme != "https"
            ):
                continue
            if re.search(
                r"\.(?:pdf|docx?|xlsx?|zip|rar)(?:[?#]|$)", candidate.url, re.IGNORECASE
            ):
                continue
            allowed += 1
            detail_response, detail_html = await self.fetch(network, candidate.url)
            detail = inspect_detail(detail_html, detail_response.url, candidate)
            content = detail.pop("content", "")
            if content:
                filename = f"samples/{_hash(entry.entry_id)[:20]}-detail-{allowed}.txt"
                _atomic(self.output / filename, content)
                detail.update(
                    contentFile=filename,
                    contentSha256=_hash(content),
                    contentCharacters=len(content),
                )
            detail["url"] = detail_response.url
            result["details"].append(detail)
            if detail.get("status") == "restricted":
                self.state["hosts"][network.host]["blocked"] = detail.get(
                    "reason", "access_challenge"
                )
                break
        result["unverifiedCrossHostUrls"] = cross_host
        if result["details"]:
            if any(item["status"] == "restricted" for item in result["details"]):
                result.update(status="restricted", reason="detail_access_restricted")
            elif all(item["status"] == "sample_readable" for item in result["details"]):
                result.update(
                    status="sample_readable", reason="static_candidate_samples_readable"
                )
            else:
                result.update(
                    status="needs_adapter", reason="detail_quality_not_verified"
                )
        elif inspection.candidates:
            result.update(
                status="needs_adapter", reason="no_permitted_html_detail_candidates"
            )
        return result

    def finish(self, entry, result):
        result.setdefault("samplingScope", self.sampling_scope(entry))
        result.update(
            entryId=entry.entry_id,
            requests=self.state["rowRequests"].get(entry.entry_id, 0),
        )
        self.state["results"][entry.entry_id] = result
        if entry.entry_id in self.state["running"]:
            self.state["running"].remove(entry.entry_id)
        _atomic(
            self.output / "rows" / f"{_hash(entry.entry_id)}.json", _json(result) + "\n"
        )
        self.persist()
        self.report()

    def sampling_scope(self, entry):
        if entry.group != "review":
            return "main_detail_samples"
        return (
            "review_detail_samples"
            if entry.entry_id in self.sample_review_entry_ids
            else "list_diagnostic_only"
        )

    async def row(self, entry):
        host = _host(entry.entry_url) if not validate_entry(entry) else ""
        lock = self.host_locks.setdefault(host, asyncio.Lock())
        async with lock, self.slots:
            if entry.entry_id in self.state["results"]:
                return
            try:
                self.check_budget()
            except SourceNetworkError:
                return
            invalid = validate_entry(entry)
            historical = historical_restriction(entry)
            if invalid or historical:
                self.finish(
                    entry,
                    {
                        "status": "invalid_input" if invalid else "restricted",
                        "reason": invalid or historical,
                        "independentlyTested": False,
                    },
                )
                return
            host_state = self.state["hosts"].setdefault(
                host, {"blocked": None, "lastRequestAt": 0}
            )
            if host_state["blocked"]:
                self.finish(
                    entry,
                    {
                        "status": "inherited_block",
                        "reason": "host_blocked:" + host_state["blocked"],
                        "independentlyTested": False,
                    },
                )
                return
            if host not in self.networks:
                self.networks[host] = CatalogNetwork(self, host)
            network = self.networks[host]
            network.row = entry
            self.state["running"].append(entry.entry_id)
            self.persist()
            try:
                remaining = self.limits.max_seconds - (
                    time.time() - self.state["startedAt"]
                )
                async with asyncio.timeout(min(self.limits.row_seconds, remaining)):
                    result = await self.inspect(entry, network)
                result["independentlyTested"] = True
            except asyncio.CancelledError:
                host_state["blocked"] = "request_cancelled"
                self.finish(
                    entry,
                    {
                        "status": "interrupted",
                        "reason": "request_cancelled",
                        "independentlyTested": True,
                    },
                )
                raise
            except (SourceNetworkError, TimeoutError) as exc:
                reason = (
                    str(exc)
                    if isinstance(exc, SourceNetworkError)
                    else "row_duration_exceeded"
                )
                if time.time() - self.state["startedAt"] >= self.limits.max_seconds:
                    reason = "batch_duration_exceeded"
                    self.state["stopReason"] = reason
                if reason in {"total_bytes_exceeded", "batch_bytes_budget_exceeded"}:
                    self.state["stopReason"] = "batch_bytes_budget_exceeded"
                global_failure = (
                    reason.startswith("batch_") or reason == "total_bytes_exceeded"
                )
                if not global_failure:
                    host_state["blocked"] = reason
                restricted = reason in {
                    "authentication_or_access_required",
                    "source_rate_limited",
                    "access_challenge",
                    "robots_disallowed",
                    "robots_returned_html_unverified",
                }
                result = {
                    "status": "restricted"
                    if restricted
                    else "budget_exhausted"
                    if global_failure
                    else "needs_adapter",
                    "reason": reason,
                    "independentlyTested": True,
                }
            except Exception as exc:  # noqa: BLE001 - unknown failures remain explicit errors, never success.
                host_state["blocked"] = "unexpected_error:" + type(exc).__name__
                result = {
                    "status": "error",
                    "reason": host_state["blocked"],
                    "independentlyTested": True,
                }
            self.finish(entry, result)

    def report(self):
        rows = []
        statuses = {}
        reasons = {}
        for entry in self.entries:
            result = self.state["results"].get(
                entry.entry_id,
                {
                    "status": "not_executed",
                    "reason": self.state["stopReason"]
                    or "not_selected_this_invocation",
                    "independentlyTested": False,
                },
            )
            rows.append({**asdict(entry), **result})
            statuses[result["status"]] = statuses.get(result["status"], 0) + 1
            reasons[result["reason"]] = reasons.get(result["reason"], 0) + 1
        summary = {
            "inputCount": len(self.entries),
            "completedCount": len(self.state["results"]),
            "unexecutedCount": len(self.entries) - len(self.state["results"]),
            "requests": self.state["requests"],
            "bytes": self.state["bytes"],
            "elapsedSeconds": round(time.time() - self.state["startedAt"], 3),
            "complete": len(self.state["results"]) == len(self.entries)
            and not self.state["stopReason"]
            and not statuses.get("interrupted"),
            "stopReason": self.state["stopReason"],
            "statuses": statuses,
            "reasons": reasons,
            "inputSha256": self.state["fingerprint"],
            "limits": self.state["limits"],
            "samplingPolicy": self.state["samplingPolicy"],
            "scope": "anonymous_static_samples_only; not native collector/history/incremental acceptance; no paid models, JS, PDF, schedules or business writes",
        }
        _atomic(self.output / "rows.jsonl", "".join(_json(row) + "\n" for row in rows))
        csv_output = io.StringIO(newline="")
        writer = csv.DictWriter(
            csv_output,
            fieldnames=[
                "entry_id",
                "group",
                "row_number",
                "entry_url",
                "name",
                "sourceId",
                "historicalVerifiedAt",
                "status",
                "reason",
                "requests",
                "independentlyTested",
            ],
        )
        writer.writeheader()
        for row in rows:
            values = {
                **{key: row.get(key, "") for key in writer.fieldnames},
                "sourceId": row["metadata"].get("sourceId", ""),
                "historicalVerifiedAt": row["metadata"].get(
                    "checkedOn", row["metadata"].get("verifiedAt", "")
                ),
            }
            writer.writerow({key: _csv_value(value) for key, value in values.items()})
        _atomic(self.output / "matrix.csv", csv_output.getvalue())
        _atomic(self.output / "summary.json", _json(summary) + "\n")
        return summary

    async def run(self, *, dry_run=False, limit=None, entry_ids=None, groups=None):
        if self._lock_fd is None:
            raise ValueError("runner is closed; instantiate with --resume")
        try:
            known = {entry.entry_id for entry in self.entries}
            if entry_ids is not None and not set(entry_ids) <= known:
                raise ValueError("unknown explicit entry IDs")
            if self.sample_review_entry_ids and (
                entry_ids is None
                or not self.sample_review_entry_ids <= set(entry_ids)
                or (groups is not None and "review" not in groups)
            ):
                raise ValueError(
                    "review detail sampling requires all opt-in IDs in this explicit entry selection"
                )
            if limit is not None and limit < 1:
                raise ValueError("limit must be positive")
            selected = [
                entry
                for entry in self.entries
                if entry.entry_id not in self.state["results"]
                and (entry_ids is None or entry.entry_id in entry_ids)
                and (groups is None or entry.group in groups)
            ]
            if limit is not None:
                selected = selected[:limit]
            if not dry_run:
                await asyncio.gather(*(self.row(entry) for entry in selected))
            return self.report()
        finally:
            self.persist()
            self.report()
            self.close()


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-csv", type=Path)
    parser.add_argument("--review-csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--entry-id", action="append")
    parser.add_argument("--group", choices=["main", "review"], action="append")
    parser.add_argument("--sample-review-entry-id", action="append")
    args = parser.parse_args()
    if args.main_csv is None and args.review_csv is None:
        parser.error("at least one explicit CSV is required")
    entries = []
    for path, group in ((args.main_csv, "main"), (args.review_csv, "review")):
        if path is not None:
            entries.extend(load_catalog(path, group))
    runner = CatalogRunner(
        entries,
        args.output,
        resume=args.resume,
        sample_review_entry_ids=args.sample_review_entry_id,
    )
    summary = asyncio.run(
        runner.run(
            dry_run=args.dry_run,
            limit=args.limit,
            entry_ids=set(args.entry_id) if args.entry_id else None,
            groups=set(args.group) if args.group else None,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
