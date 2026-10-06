import argparse
import importlib.util
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("extrio_benchmark_test", Path(__file__).resolve().parents[2] / "scripts/benchmark.py")
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def sample(run_index=1):
    return benchmark.RunSample(
        collector_index=1,
        run_index=run_index,
        run_id=f"run_{run_index}",
        status="succeeded",
        stop_reason="no_next_page",
        pages=7,
        list_pages=3,
        detail_pages=4,
        accepted=4,
        rejected=0,
        new_items=4 if run_index == 1 else 0,
        updated_items=0,
        unchanged_items=0 if run_index == 1 else 4,
        duration_seconds=0.01,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"accepted": 0, "detail_pages": 0, "new_items": 0},
        {"detail_pages": 0},
        {"accepted": 3},
        {"rejected": 1},
        {"new_items": 0, "unchanged_items": 4},
        {"updated_items": 1},
        {"status": "failed"},
    ],
)
async def test_benchmark_fails_on_missing_extraction_or_entity_work(monkeypatch, change, capsys):
    monkeypatch.setattr(benchmark, "setup_collectors", lambda *args: ["collector_test"])

    async def execute(*args):
        return [replace(sample(), **change)]

    monkeypatch.setattr(benchmark, "execute_runs", execute)
    assert await benchmark.run_benchmark(argparse.Namespace(collectors=1, pages=1), 12345) == 1
    assert "FAILED" in capsys.readouterr().err


async def test_benchmark_checks_repeat_observations_and_all_requested_runs(monkeypatch):
    monkeypatch.setattr(benchmark, "setup_collectors", lambda *args: ["collector_test"])

    async def execute(*args):
        return [sample(), sample(2)]

    monkeypatch.setattr(benchmark, "execute_runs", execute)
    args = argparse.Namespace(collectors=1, pages=2)
    assert await benchmark.run_benchmark(args, 12345) == 0

    async def incorrect_repeat(*args):
        return [sample(), replace(sample(2), new_items=4, unchanged_items=0)]

    monkeypatch.setattr(benchmark, "execute_runs", incorrect_repeat)
    assert await benchmark.run_benchmark(args, 12345) == 1

    async def missing_run(*args):
        return [sample()]

    monkeypatch.setattr(benchmark, "execute_runs", missing_run)
    assert await benchmark.run_benchmark(args, 12345) == 1


@pytest.mark.parametrize("year", [2026, 2040])
def test_benchmark_fixture_dates_stay_in_the_default_collection_window(monkeypatch, year):
    from extrio import demo

    monkeypatch.setattr(demo, "NOTICES", list(demo.NOTICES))
    now = datetime(year, 10, 6, tzinfo=UTC)
    assert benchmark.prepare_demo_fixture(now) == 4
    for notice in demo.NOTICES:
        published = datetime.fromisoformat(notice[4])
        assert 0 < (now - published).total_seconds() < 30 * 86400
        assert notice[4] in demo.tender_detail(notice[0])
