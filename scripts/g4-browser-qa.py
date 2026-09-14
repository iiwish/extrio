#!/usr/bin/env python3
"""Browser acceptance against the owned G4 fixture instance."""

import argparse
import csv
import json
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--web", default="http://127.0.0.1:5198")
    args = parser.parse_args()
    root = args.instance.resolve()
    assert root.name.startswith("g4-qa-") and args.web.startswith("http://127.0.0.1:")
    credentials = json.loads((root / "qa-login.json").read_text())
    expect.set_options(timeout=15000)
    screenshots = root / "screenshots"
    screenshots.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.web)
        page.get_by_label("用户名", exact=True).fill(credentials["username"])
        page.get_by_label("密码", exact=True).fill(credentials["password"])
        page.get_by_role("button", name="登录", exact=True).click()
        expect(page.get_by_role("link", name="采集需求", exact=True)).to_be_visible()
        page.get_by_role("link", name="采集需求", exact=True).click()
        page.get_by_role("link", name="新建需求", exact=True).click()
        page.get_by_label("需求名称", exact=True).fill("G4 browser acceptance")
        page.get_by_label("采集目标", exact=True).fill("Collect the title of the fictional local public notice.")
        page.get_by_role("button", name="保存需求", exact=True).click()
        expect(page.get_by_role("heading", name="G4 browser acceptance", exact=True)).to_be_visible()
        page.get_by_role("button", name="添加字段", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("字段名称", exact=True).fill("Title")
        dialog.get_by_label("字段标识", exact=True).fill("title")
        for label in ("必填", "去重标识", "变更检测"):
            dialog.get_by_role("checkbox", name=label, exact=True).check()
        dialog.get_by_role("button", name="确认字段", exact=True).click()
        page.get_by_role("button", name="保存字段草稿", exact=True).click()
        page.get_by_role("button", name="发布字段版本", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="发布字段版本", exact=True).click()
        expect(page.get_by_role("dialog")).not_to_be_visible()
        journey = {"collectionUrl": page.url}
        page.reload()
        expect(page.get_by_text("v1 (当前生效)", exact=True).first).to_be_visible()
        expect(page.get_by_text("已发布字段", exact=True)).to_be_visible()
        expect(page.get_by_text("草稿尚未应用，已有来源按原规则采集。", exact=True)).not_to_be_visible()
        page.get_by_role("link", name="添加来源", exact=True).click()
        state = json.loads((root / "state.json").read_text())
        page.get_by_label("手动添加，每行一个具体列表页", exact=True).fill(state["sourceUrl"] + "?case=" + uuid.uuid4().hex[:8])
        page.get_by_role("button", name="创建 1 个采集来源", exact=True).click()
        page.get_by_role("button", name="生成候选规则", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="开始生成", exact=True).click()
        publish = page.get_by_role("button", name="审核并发布", exact=True)
        expect(publish).to_be_enabled(timeout=90000)
        journey["collectorUrl"] = page.url
        expect(page.locator(".review-summary-strip").get_by_text("验证样本", exact=True).locator("..").locator("strong")).to_have_text("1")
        expect(page.get_by_text("G4 public fixture notice", exact=True)).to_be_visible()
        page.screenshot(path=str(screenshots / "review-zh-1440.png"))
        publish.click()
        expect(page.get_by_role("dialog")).to_contain_text("G4 QA")
        page.keyboard.press("Escape")
        expect(publish).to_be_focused()
        publish.click()
        page.get_by_role("dialog").get_by_role("button", name="确认发布", exact=True).click()
        if state.get("hookUrl"):
            page.get_by_role("tab", name="采集配置", exact=True).click()
            page.get_by_role("button", name="添加 Webhook", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("Webhook 地址", exact=True).fill(state["hookUrl"])
            dialog.get_by_label("签名密钥", exact=True).fill("g4-fixture-webhook")
            dialog.get_by_role("button", name="保存", exact=True).click()
            expect(dialog).not_to_be_visible()
            page.get_by_role("tab", name="概览", exact=True).click()
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/runs")) as started:
            page.get_by_role("button", name="立即运行", exact=True).click()
        assert started.value.status == 202
        run_id = started.value.json()["resourceId"]
        expect(page.get_by_role("button", name="查看完整 Run", exact=True)).to_be_visible(timeout=60000)
        if state.get("hookUrl"):
            page.get_by_role("tab", name="采集配置", exact=True).click()
            expect(page.get_by_text("已送达", exact=True)).to_be_visible(timeout=60000)
            received = [json.loads(line) for line in (root / "receiver.jsonl").read_text().splitlines()]
            assert received and all(record["valid"] for record in received)
            journey["signedDeliveries"] = len(received)
            page.get_by_role("tab", name="概览", exact=True).click()
        page.get_by_role("button", name="查看完整 Run", exact=True).click()
        expect(page.get_by_text("1 条数据已完成质量终结", exact=True)).to_be_visible(timeout=60000)
        journey["runUrl"] = page.url
        run = page.request.get(args.web + "/api/v1/runs/" + run_id).json()
        assert run["status"] == "succeeded" and run["acceptedCount"] == 1
        assert run["items"][0]["extractedData"] == {"title": "G4 public fixture notice"}
        assert run["items"][0]["lineage"]["collectionVersion"].startswith("colver_")
        journey["runId"] = run_id
        journey["collectionVersion"] = run["items"][0]["lineage"]["collectionVersion"]
        page.get_by_role("link", name="数据", exact=True).click()
        expect(page.get_by_role("heading", name="数据", exact=True)).to_be_visible()
        for format in ("CSV", "JSONL"):
            page.get_by_role("button", name="导出当前筛选的数据", exact=True).click()
            with page.expect_download() as download:
                page.get_by_role("menuitem", name="导出 " + format, exact=True).click()
            download.value.save_as(root / ("export." + format.lower()))
        records = [json.loads(line) for line in (root / "export.jsonl").read_text().splitlines() if line]
        assert any(record.get("title") == "G4 public fixture notice" for record in records)
        with (root / "export.csv").open(encoding="utf-8-sig", newline="") as handle:
            assert any("G4 public fixture notice" in row.values() for row in csv.DictReader(handle))

        # Read failures remain errors, and retry returns to the same persisted requirement.
        collection_id = journey["collectionUrl"].split("/")[-1]
        route = "**/api/v1/collections/" + collection_id
        page.route(
            route,
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"code": "QA_READ_UNAVAILABLE", "message": "G4 temporary read failure"}),
            ),
        )
        page.goto(journey["collectionUrl"])
        expect(page.get_by_role("alert")).to_be_visible()
        page.screenshot(path=str(screenshots / "read-error-zh-1440.png"))
        page.unroute(route)
        page.reload()
        expect(page.get_by_role("heading", name="G4 browser acceptance", exact=True)).to_be_visible()

        measurements = []
        for language in ("zh", "en"):
            page.goto(args.web + "/settings")
            page.get_by_role("combobox", name="界面语言", exact=True).click()
            page.get_by_role("option", name="English" if language == "en" else "中文", exact=True).click()
            for width, height in ((1440, 900), (1280, 800), (1132, 1028), (1024, 800)):
                page.set_viewport_size({"width": width, "height": height})
                for surface, url in {
                    "collection": journey["collectionUrl"],
                    "collector": journey["collectorUrl"],
                    "run": journey["runUrl"],
                    "items": args.web + "/items",
                    "settings": args.web + "/settings",
                }.items():
                    page.goto(url)
                    expect(page.locator("main")).to_be_visible()
                    page.wait_for_load_state("networkidle")
                    size = page.evaluate(
                        "({width: innerWidth, scroll: document.documentElement.scrollWidth, lang: document.documentElement.lang})"
                    )
                    assert size["scroll"] <= width + 1, (surface, language, size)
                    assert size["lang"] == ("en" if language == "en" else "zh-CN")
                    measurements.append({"surface": surface, "language": language, "width": width, "height": height, **size})
                    page.screenshot(path=str(screenshots / f"{surface}-{language}-{width}.png"))
        assert not errors, errors
        journey.update(
            {
                "runStatus": "succeeded",
                "modelEvidence": "synthetic HTTPS protocol fixture; not P28",
                "exports": ["CSV", "JSONL"],
                "measurements": measurements,
                "pageErrors": errors,
            }
        )
        (root / "browser-journey.json").write_text(json.dumps(journey, indent=2) + "\n")
        page.context.storage_state(path=str(root / "browser-state.json"))
        (root / "browser-state.json").chmod(0o600)
        print(json.dumps(journey))
        browser.close()


if __name__ == "__main__":
    main()
