"""Run inside the candidate image with benchmark.py mounted beside this file."""

import asyncio
import json
import subprocess

from benchmark import start_demo_server
from crawl4ai import CacheMode, CrawlerRunConfig
from extrio.source_clients import RestrictedBrowser
from extrio.source_network import SourceNetwork


async def fetch(port):
    network = SourceNetwork({"127.0.0.1"}, allow_localhost=True)
    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, check_robots_txt=False, delay_before_return_html=0.2)
    async with RestrictedBrowser(network) as browser:
        result = await browser.arun(f"http://127.0.0.1:{port}/demo/tenders", config)
        assert result.status_code == 200
        assert 'class="notice-title"' in result.html
    print(json.dumps({"basePipRemoved": True, "restrictedChromium": "passed", "status": result.status_code}))


if __name__ == "__main__":
    subprocess.run(
        ["/usr/local/bin/python", "-c", "import importlib.util; assert importlib.util.find_spec('pip') is None"],
        check=True,
    )
    server, port = start_demo_server()
    try:
        asyncio.run(fetch(port))
    finally:
        server.should_exit = True
