"""Exercise real keyboard events and retain detailed axe review candidates."""

import argparse
import json
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
    rows, audits, errors = [], [], []
    expect.set_options(timeout=15000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(storage_state=str(root / "browser-state.json"))
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        def capture(surface, language, width):
            dialog = page.get_by_role("dialog")
            if dialog.count():
                dialog.evaluate("el => Promise.all(el.getAnimations({subtree:true}).map(a => a.finished.catch(() => {})))")
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            page.add_script_tag(path=str(args.axe.resolve()))
            result = page.evaluate("""async () => {
                const r = await axe.run(document, {runOnly: {type: 'tag',
                    values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}});
                return {violations:r.violations, incomplete:r.incomplete.map(v => ({id:v.id,
                    nodes:v.nodes.map(n => ({target:n.target, html:n.html, summary:n.failureSummary,
                        checks:[...n.any,...n.all,...n.none].map(c=>({id:c.id,message:c.message,data:c.data}))}))}))};
            }""")
            audits.append({"surface": surface, "language": language, "width": width, **result})
            page.screenshot(path=str(root / "screenshots" / f"keyboard-{surface}-{language}-{width}.png"))
            assert not result["violations"], (surface, result["violations"])
            assert not any(rule["id"] == "aria-prohibited-attr" for rule in result["incomplete"]), surface

        def dialog_cycle(trigger, surface, language, width):
            expect(trigger).to_be_enabled()
            trigger.focus()
            expect(trigger).to_be_focused()
            page.keyboard.press("Enter")
            dialog = page.get_by_role("dialog")
            expect(dialog).to_be_visible()
            for _ in range(12):
                page.keyboard.press("Tab")
                assert page.evaluate("!!document.activeElement.closest('[role=dialog]')")
            page.keyboard.press("Shift+Tab")
            assert page.evaluate("!!document.activeElement.closest('[role=dialog]')")
            capture(surface, language, width)
            page.keyboard.press("Escape")
            expect(dialog).not_to_be_visible()
            expect(trigger).to_be_focused()
            rows.append({"case": surface + "-activation-trap-escape-return", "language": language, "width": width})

        page.goto(args.web)
        for language in ("zh", "en"):
            page.evaluate("v => localStorage.setItem('extrio.language',v)", language)
            for width, height in ((1440, 900), (1280, 800), (1132, 1028), (1024, 800)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(journey["collectionUrl"])
                page.get_by_role("button", name="编辑字段" if language == "zh" else "Edit fields", exact=True).focus()
                page.keyboard.press("Enter")
                dialog_cycle(page.get_by_role("button", name="添加字段" if language == "zh" else "Add field", exact=True),
                             "field-dialog", language, width)
                page.get_by_role("button", name="取消" if language == "zh" else "Cancel", exact=True).focus()
                page.keyboard.press("Enter")
                page.goto(args.web + "/settings?tab=system")
                first, second = page.get_by_role("tab").nth(0), page.get_by_role("tab").nth(1)
                first.focus()
                page.keyboard.press("ArrowRight")
                expect(second).to_be_focused()
                expect(second).to_have_attribute("aria-selected", "true")
                expect(page).to_have_url(args.web + "/settings?tab=models")
                rows.append({"case": "settings-tabs-keyboard-selection", "language": language, "width": width})
                dialog_cycle(page.get_by_role("button", name="添加供应商" if language == "zh" else "Add provider", exact=True),
                             "provider-dialog", language, width)
                page.goto(args.web + "/items")
                trigger = page.get_by_role(
                    "button", name="导出当前筛选的数据" if language == "zh" else "Export data with the current filters", exact=True,
                )
                trigger.focus()
                page.keyboard.press("Enter")
                expect(page.get_by_role("menu")).to_be_visible()
                page.keyboard.press("ArrowDown")
                assert page.evaluate("!!document.activeElement.closest('[role=menu]')")
                page.keyboard.press("Escape")
                expect(trigger).to_be_focused()
                rows.append({"case": "export-menu-keyboard-escape-return", "language": language, "width": width})
                capture("items", language, width)
                for surface, url in (("home", args.web), ("collector", journey["collectorUrl"])):
                    page.goto(url)
                    capture(surface, language, width)
        assert not errors, errors
        context.close()
        browser.close()
    result = {
        "cases": rows, "audits": audits, "pageErrors": errors,
        "scope": "Program-driven keyboard events; not screen-reader or full WCAG certification",
    }
    (root / "keyboard-qa.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"cases": len(rows), "audits": len(audits), "pageErrors": errors}))


if __name__ == "__main__":
    main()
