"""Isolated desktop rendering regression; all API calls use test fixtures."""
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

OUT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:5173"


def main():
    (OUT / "screenshots").mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for language in ("zh", "en"):
            context = browser.new_context()
            context.add_init_script(f"localStorage.setItem('extrio.language', '{language}')")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            fixtures = {}
            surface = "running"

            def route_api(route):
                assert route.request.method == "GET", "Test does not permit API mutations"
                path = urlparse(route.request.url).path
                if path.endswith("/auth/state"):
                    body = {"authEnabled": False, "authenticated": True, "setupRequired": False,
                            "user": {"id": "qa", "username": "qa", "displayName": "QA", "role": "administrator"}}
                elif path.endswith("/collectors"):
                    body = {"items": []}
                elif "/collectors/" in path:
                    body = {**fixtures["collector"], "status": "published" if surface == "run" else "exploring" if surface == "running" else "draft",
                            "activeOperationId": "op_execution_qa" if surface in ("running", "run") else None}
                elif path.endswith("/ai-runs"):
                    body = {"items": [{**fixtures["ai"], "status": "running" if surface in ("running", "run") else surface,
                                       "reviewStatus": "not_ready"}], "page": {"nextCursor": None}}
                elif "/operations/" in path:
                    activity = fixtures["operation"]["activity"]
                    if surface in ("running", "run"):
                        activity = [*activity[:4], {**activity[4], "status": "running", "finishedAt": None, "durationMs": None}]
                    elif surface == "failed":
                        activity = [activity[0], {**activity[1], "status": "failed"}]
                    body = {**fixtures["operation"], "kind": "run" if surface == "run" else "explore",
                            "activity": activity,
                            "status": "running" if surface in ("running", "run") else surface,
                            "phase": "fetching_details" if surface in ("running", "run") else "completed",
                            "error": {"code": "SOURCE_NETWORK_REJECTED", "message": "Page load failed", "requestId": "worker_op_execution_qa",
                                      "retryable": True, "details": {"reason": "browser_navigation_timed_out"}} if surface == "failed" else None}
                else:
                    body = {"items": []}
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

            page.route("**/api/v1/**", route_api)
            page.goto(URL + "/collectors")
            fixtures.update(page.evaluate("""async () => {
              const f = await import('/src/api/fixtures.ts');
              const collector = {...f.seedCollectors[0], candidate: null, latestRunId: null};
              const ai = {...f.seedAiRuns[0], collectorId: collector.id, operationId: 'op_execution_qa'};
              return {collector, ai, operation: {id: 'op_execution_qa', resourceType: 'collector', resourceId: collector.id,
                aiRunId: ai.id, statusUrl: '/api/v1/operations/op_execution_qa', pollAfterMs: 100, progress: 55,
                metrics: ai.activity[0].metrics, activity: ai.activity}};
            }"""))
            title = "执行日志" if language == "zh" else "Execution Log"
            view = "查看执行日志" if language == "zh" else "View execution log"
            collapse = "收起" if language == "zh" else "Minimize"
            for width, height in ((1440, 900), (1280, 800), (1132, 1028), (1024, 800)):
                page.set_viewport_size({"width": width, "height": height})
                for surface in ("running", "run", "failed", "succeeded"):
                    page.goto(URL + "/collectors/" + fixtures["collector"]["id"])
                    if surface not in ("running", "run"):
                        expect(page.get_by_role("dialog")).to_have_count(0)
                        page.get_by_role("button", name=view, exact=True).click()
                    dialog = page.get_by_role("dialog", name=title, exact=True)
                    expect(dialog).to_be_visible()
                    if surface == "failed":
                        expect(dialog).to_contain_text("browser_navigation_timed_out")
                    page.screenshot(path=str(OUT / "screenshots" / f"{surface}-{language}-{width}.png"), animations="disabled")
                    result = page.evaluate("""() => {
                      const d = document.querySelector('[role=dialog]'), r = d.getBoundingClientRect();
                      return {overflow: document.documentElement.scrollWidth > innerWidth,
                        fits: r.top >= 0 && r.left >= 0 && r.right <= innerWidth && r.bottom <= innerHeight,
                        clipped: [...d.querySelectorAll('button, code, .progress-steps span')]
                          .filter(e => e.scrollWidth > e.clientWidth + 2 && e.clientWidth > 0).map(e => e.textContent)};
                    }""")
                    assert not result["overflow"] and result["fits"] and not result["clipped"], result
                    dialog.get_by_role("button", name=collapse, exact=True).click()
                    expect(page.get_by_role("dialog")).to_have_count(0)
                    expect(page.get_by_role("button", name=view, exact=True)).to_be_visible()
                    header = page.evaluate("""() => {
                      const a = document.querySelector('.object-title').getBoundingClientRect();
                      const b = document.querySelector('.object-actions').getBoundingClientRect();
                      return {overlap: a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom,
                        overflow: document.documentElement.scrollWidth > innerWidth};
                    }""")
                    assert not header["overlap"] and not header["overflow"], header
                    page.screenshot(path=str(OUT / "screenshots" / f"collapsed-{surface}-{language}-{width}.png"), animations="disabled")
                    checks.append({"surface": surface, "language": language, "width": width, "height": height, **result})
            context.close()
        browser.close()
    assert not errors, errors
    (OUT / "ui-measurements.json").write_text(json.dumps({"checks": checks, "pageErrors": errors}, indent=2))
    print(f"Passed {len(checks)} desktop dialog and collapse checks; no real API calls.")


if __name__ == "__main__":
    main()
