"""Read-only real API/browser QA. Field changes are cancelled, never submitted."""
from pathlib import Path

from playwright.sync_api import sync_playwright

output = Path(__file__).parent
url = "http://127.0.0.1:5181/collections/collection_x_20260901_3267d726570c"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(locale="zh-CN")
    errors = []
    writes = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: writes.append(request.url) if request.method in {"POST", "PATCH", "DELETE"} else None)
    for width, height, state in [(1440, 900, "fields"), (1280, 800, "edit"),
                                 (1132, 1028, "execution"), (1024, 800, "fields-min")]:
        page.set_viewport_size({"width": width, "height": height})
        page.goto(url)
        page.get_by_role("cell", name="detailUrl", exact=True).wait_for()
        if state == "edit":
            page.get_by_role("button", name="编辑字段", exact=True).click()
            page.get_by_role("button", name="编辑字段 标题", exact=True).click()
            page.get_by_role("dialog").wait_for()
            page.get_by_label("业务说明", exact=True).fill("只读验收：此内容不会提交")
        elif state == "execution":
            page.get_by_role("tab", name="来源执行字段", exact=True).click()
            page.get_by_role("combobox", name="预览来源").click()
            page.get_by_role("option", name="www.zycg.gov.cn · 入口 2").click()
            page.get_by_role("cell", name="heading", exact=True).wait_for()
        page.screenshot(path=str(output / f"{state}-{width}x{height}.png"))
        dimensions = page.evaluate("({width: innerWidth, height: innerHeight, scroll: document.documentElement.scrollWidth})")
        assert dimensions == {"width": width, "height": height, "scroll": width}, dimensions
        if state == "edit":
            bounds = page.get_by_role("dialog").bounding_box()
            assert bounds["x"] >= 0 and bounds["y"] >= 0
            assert bounds["x"] + bounds["width"] <= width and bounds["y"] + bounds["height"] <= height
            page.get_by_role("dialog").get_by_role("button", name="取消", exact=True).click()
            page.get_by_role("button", name="取消", exact=True).click()
        print(f"PASS {state} {width}x{height}")
    assert not errors, errors
    assert not writes, writes
    browser.close()
