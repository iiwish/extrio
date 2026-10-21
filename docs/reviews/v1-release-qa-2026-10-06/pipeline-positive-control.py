"""Exercise the real pipeline with current-dated local demo fixtures."""

import asyncio
import json
import runpy
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path


def main():
    repository = Path(__file__).resolve().parents[3]
    benchmark = runpy.run_path(str(repository / "scripts/benchmark.py"))
    with tempfile.TemporaryDirectory(
        prefix="extrio-qa-positive-pipeline-"
    ) as directory:
        benchmark["configure_environment"](Path(directory))
        from extrio import demo

        # Only the synthetic HTTP fixture date changes; the actual runtime and
        # worker, contracts, publication, and collection policy stay untouched.
        published = datetime.now(UTC).isoformat()
        demo.NOTICES = [(*notice[:4], published, notice[5]) for notice in demo.NOTICES]
        server, port = benchmark["start_demo_server"]()
        try:
            collectors = benchmark["setup_collectors"](
                3, f"http://127.0.0.1:{port}/demo/tenders", "127.0.0.1"
            )
            samples = asyncio.run(benchmark["execute_runs"](collectors, 2))
            assert len(samples) == 6
            for sample in samples:
                assert sample.status == "succeeded", asdict(sample)
                assert sample.accepted == 4 and sample.detail_pages == 4, asdict(sample)
                if sample.run_index == 1:
                    assert sample.new_items == 4, asdict(sample)
                else:
                    assert sample.new_items == 0 and sample.unchanged_items == 4, (
                        asdict(sample)
                    )
            print(
                json.dumps(
                    {
                        "fixture": "current-dated synthetic local HTTP source",
                        "runtime": "real worker and Crawlee",
                        "samples": [asdict(sample) for sample in samples],
                    },
                    indent=2,
                )
            )
        finally:
            server.should_exit = True


if __name__ == "__main__":
    main()
