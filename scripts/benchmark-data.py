#!/usr/bin/env python3
"""Measure item queries on disposable SQLite and opt-in PostgreSQL databases."""

import argparse
import json
import os
import platform
import statistics
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from extrio.store import Store


@contextmanager
def isolated_store(root: Path, postgres: bool):
    admin_url = os.environ.get("EXTRIO_TEST_DATABASE_URL") if postgres else None
    database = "extrio_scale_" + uuid.uuid4().hex[:12]
    if postgres and not admin_url:
        raise RuntimeError("PostgreSQL benchmark requires EXTRIO_TEST_DATABASE_URL")
    if admin_url:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        values = conninfo_to_dict(admin_url)
        values["dbname"] = database
        # Store accepts PostgreSQL URLs; libpq parameters stay in the connection
        # object rather than appearing in benchmark output.
        from extrio.store_dialect import PostgresDialect
        store = Store(root / "unused.db")
        store.dialect = PostgresDialect(make_conninfo(**values))
    else:
        store = Store(root / "scale.db", database_url="")
    try:
        store.initialize()
        yield store
    finally:
        if admin_url:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


def seed(store: Store, count: int):
    source = store.create_collector("Scale fixture", "Query benchmark", "https://example.test/list", "example.test")
    store.save_run({"id": "run_scale", "collectorId": source["id"], "status": "succeeded", "items": []})
    with store.transaction() as connection:
        for start in range(0, count, 1000):
            batch = []
            for index in range(start, min(start + 1000, count)):
                entity = index % max(1, count // 5)
                item = {
                    "id": f"item_scale_{index:08d}", "collectorId": source["id"], "collectorName": "Scale fixture",
                    "sourceHost": "example.test", "entityKey": f"entity_{entity:08d}", "title": f"Notice {entity}",
                    "content": "Fixed fixture body. " * 50, "decision": "accepted", "revision": index // max(1, count // 5) + 1,
                    "observedAt": f"2026-09-{index // max(1, count // 5) + 1:02d}T00:00:00Z",
                }
                batch.append((item["id"], "run_scale", store.dialect.json_param(item), "2026-09-10T00:00:00Z"))
            cursor = connection.raw.cursor()
            cursor.executemany(store.dialect.translate_sql("INSERT INTO items(id, run_id, data, created_at) VALUES(?, ?, ?, ?)"), batch)
            cursor.close()


def timed(function):
    started = time.perf_counter()
    value = function()
    return value, round((time.perf_counter() - started) * 1000, 2)


def measure(store: Store, count: int):
    samples = {}
    for view in ("observations", "entities"):
        timings = []
        for _ in range(5):
            page, elapsed = timed(lambda: store.list_items_cursor(view=view, limit=100))
            assert len(page["items"]) == min(100, count if view == "observations" else count // 5)
            timings.append(elapsed)
        samples[view + "FirstPageMs"] = {"median": statistics.median(timings), "max": max(timings), "samples": timings}
    cursor, seen = None, set()
    started = time.perf_counter()
    while True:
        page = store.list_items_cursor(view="entities", limit=1000, cursor=cursor)
        for item in page["items"]:
            assert item["entityKey"] not in seen, "duplicate entity in cursor walk"
            assert item["revision"] == 5
            seen.add(item["entityKey"])
        cursor = page["nextCursor"]
        if cursor is None:
            break
    assert len(seen) == count // 5
    samples["entityCursorWalk"] = {"count": len(seen), "milliseconds": round((time.perf_counter() - started) * 1000, 2)}
    exported, elapsed = timed(lambda: sum(1 for _ in store.iter_items_export()))
    assert exported == count
    samples["observationExport"] = {"count": exported, "milliseconds": elapsed}
    return samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--postgres", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.rows < 5 or args.rows % 5:
        parser.error("--rows must be positive and divisible by 5")
    with tempfile.TemporaryDirectory(prefix="extrio-scale-") as path:
        with isolated_store(Path(path), args.postgres) as store:
            _, seed_ms = timed(lambda: seed(store, args.rows))
            report = {"date": datetime.now(UTC).isoformat(), "environment": platform.platform(), "python": platform.python_version(),
                      "database": store.dialect.name, "observations": args.rows, "bodyBytes": 1000, "seedMilliseconds": seed_ms, **measure(store, args.rows)}
    content = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
    print(content)


if __name__ == "__main__":
    main()
