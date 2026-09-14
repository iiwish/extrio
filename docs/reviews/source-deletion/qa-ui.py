"""Desktop browser regression using isolated API fixtures, never real mutations."""
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

OUT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:5173"


def main():
    (OUT / "screenshots").mkdir(parents=True, exist_ok=True)
    checks, requests, errors = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for language in ("zh", "en"):
            context = browser.new_context()
            context.add_init_script(f"localStorage.setItem('extrio.language', '{language}')")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            fixtures = {}
            state = "allowed"

            def route_api(route):
                request = route.request
                requests.append({"method": request.method, "path": urlparse(request.url).path})
                assert request.method == "GET", "No writes are permitted in UI fixtures"
                path = urlparse(request.url).path
                status = 200
                if path.endswith("/auth/state"):
                    body = {"authEnabled": False, "authenticated": True, "setupRequired": False,
                            "user": {"id": "qa", "username": "qa", "displayName": "QA", "role": "administrator"}}
                elif path.endswith("/lifecycle"):
                    body = {**fixtures["plan"], "blockers": ["TASK_ALREADY_ACTIVE"] if state == "blocked" else [],
                            "deleteBlockers": ["TASK_ALREADY_ACTIVE"] if state == "blocked" else []}
                    if state == "error":
                        status, body = 503, {"code": "UNAVAILABLE", "message": "Preview unavailable", "retryable": True, "requestId": "qa"}
                elif path.endswith("/collectors"):
                    body = {"items": [fixtures["collector"]] if fixtures else []}
                elif "/ai-runs/" in path:
                    body = fixtures["ai"]
                elif "/runs/" in path:
                    body = ({"mode": "sampled", "state": "expired", "fileCount": 1, "totalBytes": 0,
                             "expiresAt": "2026-01-01T00:00:00Z", "canReplay": False,
                             "replayReason": "complete_replayable_evidence_unavailable"} if path.endswith("/evidence") else fixtures["run"])
                elif "/items/" in path:
                    body = fixtures["item"]
                else:
                    body = {"items": []}
                route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

            page.route("**/api/v1/**", route_api)
            page.goto(URL + "/collectors")
            fixtures.update(page.evaluate("""async () => {
              const f = await import('/src/api/fixtures.ts');
              const collector = {...f.seedCollectors[0], name: '删除验证来源', latestRunId: null};
              return {collector, run: {...f.seedRuns[0], collectorDeleted: true},
                ai: {...f.seedAiRuns[0], collectorDeleted: true},
                item: {...f.seedRuns[0].items[0], collectorDeleted: true},
                plan: {collectorId: collector.id, collectorName: collector.name, sourceUrl: collector.sourceUrl,
                  collectionName: collector.collectionName, lifecycle: 'active', blockers: [], deleteBlockers: [],
                  historyCounts: {operations: 13, ai_runs: 13, rules: 4, runs: 8, items: 128, sinks: 2, deliveries: 21},
                  hasHistory: true, scheduleEnabled: true, planDigest: 'qa-only'}};
            }"""))
            deleted_label = "来源已删除" if language == "zh" else "Source deleted"
            delete_label = "删除来源" if language == "zh" else "Delete source"
            name_label = "输入来源名称确认" if language == "zh" else "Type source name to confirm"
            for width, height in ((1440, 900), (1280, 800), (1132, 1028), (1024, 800)):
                page.set_viewport_size({"width": width, "height": height})
                for surface in ("allowed", "blocked", "ai", "run", "item"):
                    state = surface
                    if surface in ("allowed", "blocked"):
                        page.goto(URL + "/collectors")
                        menu = "管理采集来源：删除验证来源" if language == "zh" else "Manage source: 删除验证来源"
                        page.get_by_role("button", name=menu, exact=True).click()
                        page.get_by_role("menuitem", name=delete_label, exact=True).click()
                        dialog = page.get_by_role("dialog")
                        expect(dialog).to_be_visible()
                        button = dialog.get_by_role("button", name=delete_label, exact=True)
                        expect(button).to_be_disabled()
                        if surface == "allowed":
                            input_box = dialog.get_by_role("textbox", name=name_label)
                            expect(input_box).to_be_visible()
                            input_box.fill("删除验证来源")
                            expect(button).to_be_enabled()
                            expect(dialog.get_by_role("region", name="保留的历史" if language == "zh" else "Retained history")).to_contain_text("128")
                        else:
                            expect(dialog.get_by_text("有排队或执行中的任务" if language == "zh" else "A task is queued or processing", exact=True)).to_be_visible()
                            expect(dialog.get_by_role("textbox")).to_have_count(0)
                    else:
                        path = {"ai": f"/ai-runs/{fixtures['ai']['id']}?section=evidence",
                                "run": f"/runs/{fixtures['run']['id']}?section=quality",
                                "item": f"/items/{fixtures['item']['id']}?section=lineage"}[surface]
                        page.goto(URL + path)
                        expect(page.get_by_text(deleted_label, exact=True)).to_be_visible()
                        expect(page.locator('a[href^="/collectors/"]')).to_have_count(0)
                    page.screenshot(path=str(OUT / "screenshots" / f"{surface}-{language}-{width}.png"), animations="disabled")
                    result = page.evaluate("""() => ({
                      overflow: document.documentElement.scrollWidth > innerWidth,
                      clipped: [...document.querySelectorAll('.collector-management-dialog button, .management-history dt, .management-history dd')]
                        .filter(e => e.scrollWidth > e.clientWidth + 2).map(e => e.textContent),
                      dialogFits: [...document.querySelectorAll('[role=dialog]')].every(e => {
                        const r=e.getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight && r.left>=0 && r.right<=innerWidth;
                      })})""")
                    checks.append({"surface": surface, "language": language, "width": width, "height": height, **result})
                    assert not result["overflow"] and not result["clipped"] and result["dialogFits"], checks[-1]
            context.close()
        browser.close()
    assert not errors, errors
    (OUT / "ui-measurements.json").write_text(json.dumps({"checks": checks, "requests": requests, "pageErrors": errors}, indent=2), encoding="utf-8")
    print(f"Passed {len(checks)} desktop checks; all API requests were intercepted GET fixtures.")


if __name__ == "__main__":
    main()
