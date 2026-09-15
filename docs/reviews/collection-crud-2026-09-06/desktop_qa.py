"""Read-only desktop QA against the local, real frontend and API."""
from pathlib import Path

from playwright.sync_api import sync_playwright


output = Path(__file__).parent
url = "http://127.0.0.1:5181"
detail = f"{url}/collections/collection_x_20260901_3267d726570c"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(locale="zh-CN")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    for width, height, state in [(1440, 900, "detail"), (1280, 800, "edit"),
                                 (1132, 1028, "archive"), (1024, 800, "new")]:
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{url}/collections/new" if state == "new" else detail)
        if state == "new":
            page.get_by_role("textbox", name="需求名称").wait_for()
        else:
            page.get_by_role("button", name="编辑需求", exact=True).wait_for()
            assert page.get_by_role("button", name="删除需求", exact=True).count() == 0
            if state in {"edit", "archive"}:
                page.get_by_role("button", name="编辑需求" if state == "edit" else "归档需求", exact=True).click()
                page.get_by_role("dialog").wait_for()
        page.screenshot(path=str(output / f"{state}-{width}x{height}.png"))
        dimensions = page.evaluate("({width: innerWidth, height: innerHeight, scroll: document.documentElement.scrollWidth})")
        assert dimensions == {"width": width, "height": height, "scroll": width}, dimensions
        if state in {"edit", "archive"}:
            bounds = page.get_by_role("dialog").bounding_box()
            assert bounds["x"] >= 0 and bounds["y"] >= 0
            assert bounds["x"] + bounds["width"] <= width
            assert bounds["y"] + bounds["height"] <= height
            page.get_by_role("button", name="取消", exact=True).click()
        print(f"PASS {state} {width}x{height}: no horizontal overflow")
    assert not errors, errors
    browser.close()
