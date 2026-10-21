"""Current-run desktop accessibility and adversarial-content probes."""

import argparse
import json
import secrets
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--web", required=True)
    parser.add_argument("--axe", type=Path, required=True)
    args = parser.parse_args()
    root = args.instance.resolve()
    assert root.name.startswith("g4-qa-") and args.web.startswith("http://127.0.0.1:")
    journey = json.loads((root / "browser-journey.json").read_text())
    credentials = json.loads((root / "qa-login.json").read_text())
    rows, errors, behavior = [], [], []
    expect.set_options(timeout=15000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        def capture(surface, language, width):
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            page.add_script_tag(path=str(args.axe.resolve()))
            audit = page.evaluate("""async () => {
                const result = await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}});
                return {violations: result.violations.map(v => ({id: v.id, impact: v.impact, description: v.description, helpUrl: v.helpUrl,
                    nodes: v.nodes.map(n => ({target: n.target, html: n.html, failureSummary: n.failureSummary}))})),
                    incomplete: result.incomplete.map(v => ({id: v.id, count: v.nodes.length})), passes: result.passes.length,
                    axeVersion: result.testEngine.version};
            }""")
            geometry = page.evaluate(
                "({width: innerWidth, scrollWidth: document.documentElement.scrollWidth, lang: document.documentElement.lang})"
            )
            path = root / "screenshots" / f"audit-{surface}-{language}-{width}.png"
            page.screenshot(path=str(path), full_page=True)
            rows.append(
                {
                    "surface": surface,
                    "language": language,
                    "width": width,
                    "geometry": geometry,
                    "screenshot": path.name,
                    **audit,
                }
            )

        page.goto(args.web)
        expect(page.get_by_label("用户名", exact=True)).to_be_visible()
        capture("login", "zh", 1440)
        page.get_by_label("用户名", exact=True).fill(credentials["username"])
        page.get_by_label("密码", exact=True).fill("incorrect-qa-password")
        page.get_by_role("button", name="登录", exact=True).click()
        expect(page.get_by_role("alert")).to_be_visible()
        behavior.append({"case": "wrong-password-visible-error", "status": "passed"})
        page.get_by_label("密码", exact=True).fill(credentials["password"])
        page.get_by_role("button", name="登录", exact=True).click()
        expect(page.get_by_role("link", name="采集需求", exact=True)).to_be_visible()

        payload = (
            '<img src=x onerror="window.__qaXss=1">'
            + "LongUnbrokenOperationalRequirement" * 4
        )
        payload = payload[:200]
        created = page.request.post(
            args.web + "/api/v1/collections",
            data={"name": payload, "intent": "QA HTML remains inert source content"},
            headers={"Idempotency-Key": "qa-browser-xss-" + secrets.token_hex(8)},
        )
        assert created.status == 201, created.text()
        long_url = args.web + "/collections/" + created.json()["id"]
        surfaces = {
            "home": args.web,
            "collections": args.web + "/collections",
            "long-content": long_url,
            "new-collector": args.web + "/collectors/new",
            "collector": journey["collectorUrl"],
            "run": journey["runUrl"],
            "ai-run": journey["aiRunUrl"],
            "items": args.web + "/items",
            "item": journey["itemUrl"],
            "settings": args.web + "/settings",
            "models": args.web + "/settings?tab=models",
        }
        for language in ("zh", "en"):
            page.evaluate(
                "language => localStorage.setItem('extrio.language', language)",
                language,
            )
            for width, height in ((1440, 900), (1024, 800)):
                page.set_viewport_size({"width": width, "height": height})
                for surface, url in surfaces.items():
                    page.goto(url)
                    expect(page.locator("main")).to_be_visible()
                    capture(surface, language, width)
                    if surface == "long-content":
                        expect(
                            page.get_by_role("heading", name=payload, exact=True)
                        ).to_be_visible()
                        assert page.evaluate("window.__qaXss || 0") == 0
                        assert page.locator('main img[src="x"]').count() == 0
                        behavior.append(
                            {
                                "case": "html-content-inert",
                                "language": language,
                                "width": width,
                                "status": "passed",
                            }
                        )

        context.close()
        browser.close()
    report = {
        "axeVersion": rows[0]["axeVersion"],
        "scans": rows,
        "behaviors": behavior,
        "pageErrors": errors,
        "overflow": [
            {
                "surface": row["surface"],
                "language": row["language"],
                "width": row["width"],
                **row["geometry"],
            }
            for row in rows
            if row["geometry"]["scrollWidth"] > row["width"] + 1
        ],
        "violationInstances": sum(len(row["violations"]) for row in rows),
    }
    (root / "browser-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "scans": len(rows),
                "violationInstances": report["violationInstances"],
                "overflow": report["overflow"],
                "pageErrors": errors,
                "behaviors": behavior,
            },
            indent=2,
        )
    )
    raise SystemExit(
        1 if errors or report["overflow"] or report["violationInstances"] else 0
    )


if __name__ == "__main__":
    main()
