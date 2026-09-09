"""Desktop visual checks without business writes."""
from pathlib import Path

from playwright.sync_api import sync_playwright

output = Path(__file__).parent
url = "http://127.0.0.1:5181/collections/collection_x_20260901_3267d726570c"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(locale="zh-CN")
    errors, writes = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: writes.append(request.url) if request.method in {"POST", "PATCH", "DELETE"} else None)
    for width, height, state in [(1440, 900, "fields"), (1280, 800, "differences"),
                                 (1132, 1028, "edit"), (1024, 800, "fields-min")]:
        page.set_viewport_size({"width": width, "height": height})
        page.goto(url)
        page.get_by_text("detailUrl", exact=True).wait_for()
        assert page.get_by_role("tab").count() == 2
        assert page.get_by_role("table").count() == 1
        assert page.get_by_text("title", exact=True).count() == 1
        if state == "differences":
            page.get_by_role("button", name="查看 详情链接 的来源", exact=True).click()
            page.get_by_role("dialog").wait_for()
        elif state == "edit":
            page.get_by_role("button", name="编辑字段", exact=True).click()
            page.get_by_role("button", name="编辑字段 标题", exact=True).click()
            page.get_by_role("dialog").wait_for()
        page.screenshot(path=str(output / f"{state}-{width}x{height}.png"), animations="disabled")
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        if state in {"differences", "edit"}:
            box = page.get_by_role("dialog").bounding_box()
            assert box["x"] >= 0 and box["y"] >= 0
            assert box["x"] + box["width"] <= width and box["y"] + box["height"] <= height
            page.get_by_role("dialog").get_by_role("button", name="关闭", exact=True).click()
        if state == "edit":
            page.get_by_role("button", name="取消", exact=True).click()
        print(f"PASS {state} {width}x{height}")
    assert not errors, errors
    assert not writes, writes
    browser.close()
