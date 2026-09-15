"""Isolated browser fixtures: no requests mutate the real application database."""
import json
from copy import deepcopy
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "screenshots"
URL = "http://127.0.0.1:5173"
STAMP = "2026-09-11T07:00:00Z"
LIMITS = {"contextTokens": 32768, "maxInputTokens": 24000, "maxOutputTokens": 4096, "reasoningTokens": 1024}
CONFIG = {
    "providers": [{"id": "provider_qa", "name": "QA provider", "provider": "custom", "baseUrl": "https://example.test/v1", "enabled": True, "credentialConfigured": True, "updatedAt": STAMP}],
    "models": [{"id": "model_qa", "providerId": "provider_qa", "modelId": "qa-context-model", "enabled": True, "isDefault": True, "updatedAt": STAMP, "limits": LIMITS}],
    "defaultModelId": "model_qa", "updatedAt": STAMP,
}
EVIDENCE = {
    "version": "adaptive-dom-v1", "phase": "validated", "limitsSource": "configured", "validated": True,
    "budget": {"calls": 4, "maxCalls": 8, "inputTokens": 25180, "outputTokens": 3251, "maxInputTokens": 120000, "maxOutputTokens": 16000, "contextTokens": 32768, "tokenMethod": "utf8_upper_estimate", "elapsedSeconds": 57, "maxSeconds": 240, "stopReason": None},
    "pages": [{"pageId": page, "indexedNodes": 840, "readNodes": 3, "readFragmentChars": 4928} for page in ("list-1", "detail-1", "detail-2", "detail-3")],
    "reads": [{"pageId": "detail-1", "nodeId": "n783", "action": "read_nodes", "digest": "sha256:fixture", "start": 0, "end": 2400, "complete": False}, {"pageId": "detail-1", "nodeId": "n783", "action": "read_nodes", "digest": "sha256:fixture", "start": 2400, "end": 3480, "complete": True}],
    "validation": [],
}
RUN = {
    "id": "ai_run_qa", "operationId": "op_qa", "collectorId": "collector_qa", "collectorName": "QA source",
    "sourceUrl": "https://example.test/public/notices", "kind": "rule_repair", "trigger": "manual_repair", "initiatedBy": "user_qa",
    "status": "succeeded", "phase": "completed", "progress": 100, "resultStatus": "candidate_ready", "reviewStatus": "ready_review", "attemptCount": 1,
    "modelSummary": {"invocationCount": 4, "promptTokens": 25180, "completionTokens": 3251, "totalTokens": 28431, "estimatedCost": None},
    "validationSummary": {"acceptedSamples": 3, "rejectedSamples": 0, "warningCount": 0}, "candidateRuleDigest": "sha256:fixture", "publishedRuleVersionId": None,
    "createdAt": STAMP, "startedAt": STAMP, "finishedAt": STAMP, "durationMs": 57000, "error": None, "attempts": [], "evidence": EVIDENCE,
}


def main():
    OUT.mkdir(exist_ok=True)
    measurements = []
    requests = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for language in ("zh", "en"):
            context = browser.new_context()
            context.add_init_script(f"localStorage.setItem('extrio.language', '{language}')")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def route_api(route):
                request = route.request
                requests.append({"method": request.method, "url": request.url})
                assert request.method == "GET", "QA must not mutate any real API"
                if "/auth/state" in request.url:
                    body = {"authEnabled": False, "authenticated": True, "setupRequired": False, "user": {"id": "user_qa", "username": "qa", "displayName": "QA", "role": "administrator"}}
                elif "/settings/models" in request.url:
                    body = CONFIG
                elif "/ai-runs/" in request.url:
                    body = RUN
                else:
                    body = {"items": []}
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

            page.route("**/api/v1/**", route_api)
            for width, height in ((1440, 900), (1280, 800), (1132, 1028), (1024, 800)):
                page.set_viewport_size({"width": width, "height": height})
                for surface in ("process", "evidence", "model"):
                    if surface == "model":
                        page.goto(URL + "/settings?tab=models")
                        page.get_by_role("button", name="qa-context-model 模型操作" if language == "zh" else "qa-context-model model actions", exact=True).click()
                        page.get_by_role("menuitem", name="编辑模型" if language == "zh" else "Edit model", exact=True).click()
                        expect(page.get_by_role("dialog")).to_be_visible()
                        expect(page.get_by_role("spinbutton", name="上下文窗口" if language == "zh" else "Context window", exact=True)).to_have_value("32768")
                    else:
                        page.goto(URL + "/ai-runs/ai_run_qa?section=" + surface)
                        expect(page.locator(".adaptive-evidence")).to_be_visible()
                        if surface == "evidence":
                            page.locator(".adaptive-reads summary").click()
                    page.screenshot(path=str(OUT / f"{surface}-{language}-{width}.png"), animations="disabled")
                    result = page.evaluate("""() => ({overflow: document.documentElement.scrollWidth > innerWidth,
                      clipped: [...document.querySelectorAll('.adaptive-table th, .adaptive-table td, .settings-dialog label')].filter(e => e.scrollWidth > e.clientWidth + 2).map(e => e.textContent),
                      dialogFits: [...document.querySelectorAll('[role=dialog]')].every(e => { const r=e.getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight && r.left>=0 && r.right<=innerWidth; })})""")
                    measurements.append({"surface": surface, "language": language, "width": width, "height": height, **result})
                    assert not result["overflow"] and not result["clipped"] and result["dialogFits"], measurements[-1]
            original_run = deepcopy(RUN)
            for state in ('failed', 'historical'):
                RUN.clear()
                RUN.update(deepcopy(original_run))
                if state == 'failed':
                    RUN.update(status='failed', resultStatus='no_candidate', reviewStatus='not_ready', candidateRuleDigest=None)
                    RUN['evidence'].update(phase='failed', validated=False, validation=[{'code': 'TITLE_MISMATCH', 'field': 'title', 'sample': 1}])
                    RUN['evidence']['budget'].update(calls=8, stopReason='MODEL_CALL_BUDGET_EXCEEDED')
                else:
                    RUN.pop('evidence', None)
                for width, height in ((1440, 900), (1280, 800), (1132, 1028), (1024, 800)):
                    page.set_viewport_size({'width': width, 'height': height})
                    page.goto(URL + '/ai-runs/ai_run_qa?section=evidence')
                    expect(page.locator('.run-proof-section')).to_be_visible()
                    if state == 'failed':
                        expect(page.locator('.adaptive-evidence .ai-run-error')).to_be_visible()
                    else:
                        expect(page.locator('.adaptive-evidence')).to_have_count(0)
                    page.screenshot(path=str(OUT / f'{state}-{language}-{width}.png'), animations='disabled')
                    overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    measurements.append({'surface': state, 'language': language, 'width': width, 'height': height, 'overflow': overflow})
                    assert not overflow
            RUN.clear()
            RUN.update(original_run)
            assert not errors, errors
            context.close()
        browser.close()
    (ROOT / "ui-measurements.json").write_text(json.dumps({"measurements": measurements, "requests": len(requests), "realApiWrites": 0}, indent=2) + "\n")
    print(f"{len(measurements)} desktop/language/surface checks passed; zero real API writes")


if __name__ == "__main__":
    main()
