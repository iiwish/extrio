"""Collector lifecycle acceptance against an owned g4-qa-* instance only."""

import argparse
import json
import os
import signal
import time
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--web", default="http://127.0.0.1:5199")
    args = parser.parse_args()
    root = args.instance.resolve()
    assert root.name.startswith("g4-qa-") and args.web.startswith("http://127.0.0.1:")
    state = json.loads((root / "state.json").read_text())
    credentials = json.loads((root / "qa-login.json").read_text())
    screenshots = root / "lifecycle-screenshots"
    screenshots.mkdir(exist_ok=True)
    expect.set_options(timeout=20000)
    run_tag = uuid.uuid4().hex[:8]
    evidence = {"syntheticModel": True, "checks": [], "measurements": [], "pageErrors": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda error: evidence["pageErrors"].append(str(error)))
        page.goto(args.web)
        page.get_by_label("用户名", exact=True).fill(credentials["username"])
        page.get_by_label("密码", exact=True).fill(credentials["password"])
        page.get_by_role("button", name="登录", exact=True).click()
        expect(page.get_by_role("link", name="采集需求", exact=True)).to_be_visible()

        def request(method, path, body=None):
            response = page.request.fetch(args.web + "/api/v1" + path, method=method, data=body,
                                          headers={"Idempotency-Key": str(uuid.uuid4())})
            assert response.ok, (method, path, response.status, response.text())
            return response.json()

        def requirement(name, description):
            value = request("POST", "/collections", {"name": name, "intent": "Collect the title of the local fictional public notice."})
            field = {"key": "title", "label": "标题", "type": "string", "required": True,
                     "identity": True, "fingerprint": True, "description": description}
            value = request("PATCH", f"/collections/{value['id']}", {"revision": value["revision"], "fieldDraft": {"fields": [field]}})
            request("POST", f"/collections/{value['id']}/publish-version", {"revision": value["revision"], "note": "Isolated lifecycle QA"})
            return request("GET", f"/collections/{value['id']}")

        original = requirement("生命周期原需求 " + run_tag, "原始标题")
        target = requirement("跨需求调整目标：公开公告与采购项目完整标题验证 " + run_tag, "目标标题：保留完整项目名称，不截断业务主体。")

        def add_source(suffix):
            page.goto(args.web + f"/collections/{original['id']}")
            page.get_by_role("button", name="添加来源", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("手动添加，每行一个具体列表页", exact=True).fill(state["sourceUrl"] + "?case=" + run_tag + suffix)
            with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/collectors/batch")) as created:
                dialog.get_by_role("button", name="添加来源", exact=True).click()
            assert created.value.status == 200, created.value.text()
            source = created.value.json()["results"][0]["collector"]
            expect(dialog).not_to_be_visible()
            expect(page.locator(".collection-sources-table")).to_contain_text(source["name"])
            return source

        def menu(label, source_name=None):
            buttons = page.get_by_role("button", name="管理采集来源：" + source_name, exact=True) if source_name else page.locator(".object-actions .collector-management-trigger")
            buttons.click()
            page.get_by_role("menuitem", name=label, exact=True).click()

        def goto_source(source, suffix=""):
            page.goto(args.web + f"/collectors/{source['id']}" + suffix)
            expect(page.locator(".object-title h1")).to_be_visible()

        def capture(name):
            page.wait_for_function("document.fonts.status === 'loaded'")
            size = page.evaluate("({width: innerWidth, height: innerHeight, scroll: document.documentElement.scrollWidth})")
            assert size["scroll"] <= size["width"] + 1, (name, size)
            if name.startswith("source-list-"):
                columns = page.evaluate("""() => {
                  const head = [...document.querySelector('.collector-list-grid.object-list-head').children];
                  const row = [...document.querySelector('.collector-list-row').children];
                  return head.map((cell, i) => ({head: cell.getBoundingClientRect().x, row: row[i].getBoundingClientRect().x}));
                }""")
                assert all(abs(column["head"] - column["row"]) <= 1 for column in columns[:5]), (name, columns)
            dialog = page.get_by_role("dialog")
            if dialog.count():
                box = dialog.bounding_box()
                assert box and box["x"] >= 0 and box["y"] >= 0 and box["x"] + box["width"] <= size["width"] + 1 and box["y"] + box["height"] <= size["height"] + 1, (name, box)
            evidence["measurements"].append({"surface": name, **size})
            page.screenshot(path=str(screenshots / (name + ".png")), animations="disabled")

        def completed_run(run_id):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                value = request("GET", f"/runs/{run_id}")
                if value["status"] in {"succeeded", "failed", "partially_succeeded", "cancelled", "timed_out"}:
                    return value
                time.sleep(0.5)
            raise AssertionError(f"Run {run_id} did not finish")

        empty = add_source("-empty")
        goto_source(empty)
        menu("编辑来源")
        dialog = page.get_by_role("dialog")
        renamed = "可删除空来源 " + run_tag
        dialog.get_by_label("采集来源名称", exact=True).fill(renamed)
        dialog.get_by_role("button", name="保存信息", exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(page.locator(".object-title h1")).to_have_text(renamed)
        empty = request("GET", f"/collectors/{empty['id']}")
        assert empty["managementRevision"] == 1
        page.goto(args.web + "/collectors?q=" + run_tag)
        page.get_by_role("link", name=renamed, exact=False).click()
        menu("删除来源")
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_role("button", name="删除来源", exact=True)).to_be_disabled()
        dialog.get_by_label("输入来源名称确认", exact=True).fill(renamed)
        capture("delete-empty-zh-1440")
        dialog.get_by_role("button", name="删除来源", exact=True).click()
        expect(page).to_have_url(args.web + "/collectors?q=" + run_tag)
        assert page.request.get(args.web + f"/api/v1/collectors/{empty['id']}").status == 404
        evidence["checks"].append("add inside requirement; edit revision; exact-name empty delete; return to filtered list")

        source = add_source("-history")
        goto_source(source)
        page.get_by_role("button", name="生成候选规则", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="开始生成", exact=True).click()
        publish = page.get_by_role("button", name="审核并发布", exact=True)
        expect(publish).to_be_enabled(timeout=90000)
        publish.click()
        page.get_by_role("dialog").get_by_role("button", name="确认发布", exact=True).click()
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/runs")) as running:
            page.get_by_role("button", name="立即运行", exact=True).click()
        assert running.value.status == 202
        old_run_id = running.value.json()["resourceId"]
        expect(page.get_by_role("button", name="查看完整 Run", exact=True)).to_be_visible(timeout=60000)
        old_run = completed_run(old_run_id)
        assert old_run["status"] == "succeeded" and old_run["acceptedCount"] == 1
        assert old_run["collectionAttribution"]["collectionId"] == original["id"]
        old_item = request("GET", f"/items/{old_run['items'][0]['id']}")
        source = request("GET", f"/collectors/{source['id']}")
        menu("删除来源")
        expect(page.get_by_role("dialog")).to_contain_text("存在采集运行记录")
        expect(page.get_by_role("dialog").get_by_role("button", name="删除来源", exact=True)).to_be_disabled()
        capture("delete-blocked-zh-1440")
        page.keyboard.press("Escape")

        # Lose the first committed response; retry must replay its durable receipt.
        keys = []
        lifecycle_url = "**/api/v1/collectors/" + source["id"] + "/lifecycle"

        def lost_response(route):
            if route.request.method != "POST":
                route.continue_()
                return
            keys.append(route.request.headers.get("idempotency-key"))
            if len(keys) == 1:
                response = route.fetch()
                assert response.status == 200
                route.abort("failed")
            else:
                route.continue_()

        page.route(lifecycle_url, lost_response)
        menu("归档来源")
        dialog = page.get_by_role("dialog")
        dialog.get_by_role("button", name="归档来源", exact=True).click()
        expect(dialog.get_by_role("alert")).to_be_visible()
        capture("archive-lost-response-zh-1440")
        dialog.get_by_role("button", name="归档来源", exact=True).click()
        expect(dialog).not_to_be_visible()
        page.unroute(lifecycle_url)
        assert len(keys) == 2 and keys[0] and keys[0] == keys[1]
        assert request("GET", f"/collectors/{source['id']}")["lifecycle"] == "archived"
        expect(page.get_by_role("button", name="立即运行", exact=True)).not_to_be_visible()
        page.goto(args.web + "/collectors?q=" + run_tag)
        expect(page.locator(".collector-row-shell")).to_have_count(0)
        page.get_by_label("来源生命周期", exact=True).select_option("archived")
        expect(page.locator(".collector-row-shell")).to_have_count(1)
        capture("archived-list-zh-1440")
        menu("恢复来源", source["name"])
        page.get_by_role("dialog").get_by_role("button", name="恢复来源", exact=True).click()
        expect(page.get_by_role("dialog")).not_to_be_visible()
        restored = request("GET", f"/collectors/{source['id']}")
        assert restored["lifecycle"] == "active" and not restored["schedule"]["enabled"]
        evidence["checks"].append("history deletion blocked; archive lost-response retry reused key; archived filter; restore leaves schedule disabled")

        goto_source(source)
        menu("调整所属需求")
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("目标需求", exact=True).select_option(target["id"])
        expect(dialog.get_by_role("checkbox")).to_have_count(1)
        expect(dialog.get_by_role("button", name="调整所属需求", exact=True)).to_be_disabled()
        for width, height in ((1440, 900), (1280, 800), (1132, 1028), (1024, 800)):
            page.set_viewport_size({"width": width, "height": height})
            capture(f"reassignment-zh-{width}")
        dialog.get_by_role("checkbox").check()
        dialog.get_by_role("button", name="调整所属需求", exact=True).click()
        expect(dialog).not_to_be_visible()
        moved = request("GET", f"/collectors/{source['id']}")
        assert moved["collectionId"] == target["id"] and moved["activeRuleVersion"] is None and moved["candidate"] is None
        assert not moved["schedule"]["enabled"] and moved["status"] == "draft"
        assert request("GET", f"/runs/{old_run_id}") == old_run
        assert request("GET", f"/items/{old_item['id']}") == old_item
        assert request("GET", f"/collections/{original['id']}")["sourceCount"] == 0
        assert request("GET", f"/collections/{target['id']}")["sourceCount"] == 1
        page.goto(args.web + f"/runs/{old_run_id}")
        expect(page.locator(".history-attribution").get_by_role("link", name=original["name"], exact=True)).to_be_visible()
        capture("original-run-attribution-zh-1024")
        evidence["checks"].append("confirmed field difference; source moved; old run/item unchanged and linked to original requirement; both source counts refreshed")

        goto_source(source)
        page.get_by_role("button", name="生成候选规则", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="开始生成", exact=True).click()
        publish = page.get_by_role("button", name="审核并发布", exact=True)
        expect(publish).to_be_enabled(timeout=90000)
        publish.click()
        page.get_by_role("dialog").get_by_role("button", name="确认发布", exact=True).click()
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/runs")) as running:
            page.get_by_role("button", name="立即运行", exact=True).click()
        new_run_id = running.value.json()["resourceId"]
        expect(page.get_by_role("button", name="查看完整 Run", exact=True)).to_be_visible(timeout=60000)
        new_run = completed_run(new_run_id)
        assert new_run["status"] == "succeeded" and new_run["collectionAttribution"]["collectionId"] == target["id"]
        assert new_run["ruleVersion"] != old_run["ruleVersion"]
        evidence["checks"].append("recompile and human publish required; new successful run attributed to target with new immutable rule version")

        # Pause only the owned QA worker to exercise a real durable queued task.
        os.kill(state["workerPid"], signal.SIGSTOP)
        try:
            operation = request("POST", f"/collectors/{source['id']}/explorations", {})
            goto_source(source)
            menu("归档来源")
            expect(page.get_by_role("dialog")).to_contain_text("有排队或执行中的任务")
            expect(page.get_by_role("dialog").get_by_role("button", name="归档来源", exact=True)).to_be_disabled()
            capture("queued-blocker-zh-1024")
            page.keyboard.press("Escape")
            request("POST", f"/operations/{operation['id']}/cancel")
        finally:
            os.kill(state["workerPid"], signal.SIGCONT)
        evidence["checks"].append("actual queued operation prevents archive while owned worker is paused")

        for language in ("zh", "en"):
            if language == "en":
                page.goto(args.web + "/settings")
                page.get_by_role("combobox", name="界面语言", exact=True).click()
                page.get_by_role("option", name="English", exact=True).click()
            for width, height in ((1440, 900), (1280, 800), (1132, 1028), (1024, 800)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(args.web + "/collectors?q=" + run_tag)
                expect(page.locator(".collector-row-shell")).to_have_count(1)
                capture(f"source-list-{language}-{width}")
                page.locator(".collector-management-trigger").click()
                capture(f"source-menu-{language}-{width}")
                page.keyboard.press("Escape")
                goto_source(source, "?section=config")
                capture(f"source-config-{language}-{width}")
                if language == "en":
                    page.locator(".object-actions .collector-management-trigger").click()
                    page.get_by_role("menuitem", name="Change requirement", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    dialog.get_by_label("Target requirement", exact=True).select_option(original["id"])
                    expect(dialog.get_by_role("checkbox")).to_have_count(1)
                    capture(f"reassignment-en-{width}")
                    page.keyboard.press("Escape")
        assert not evidence["pageErrors"], evidence["pageErrors"]
        evidence.update(sourceId=source["id"], originalRequirementId=original["id"], targetRequirementId=target["id"],
                        oldRunId=old_run_id, newRunId=new_run_id, idempotencyReplayed=True)
        (root / "collector-lifecycle-browser.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
        page.context.storage_state(path=str(root / "lifecycle-browser-state.json"))
        (root / "lifecycle-browser-state.json").chmod(0o600)
        print(json.dumps(evidence, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
