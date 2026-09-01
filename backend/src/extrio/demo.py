from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/demo", tags=["Local demo source"])


NOTICES = [
    ("4f82", "海淀区政务云扩容服务公开招标公告", "北京市海淀区政务服务管理局", "海淀区", "2026-08-30T09:20:00+08:00", "¥ 3,280,000"),
    ("a19c", "城市副中心数据治理平台采购公告", "北京市通州区大数据中心", "通州区", "2026-08-30T08:45:00+08:00", "¥ 1,860,000"),
    ("93d1", "公共资源交易数字化升级项目招标公告", "北京市公共资源交易中心", "北京市", "2026-08-29T17:18:00+08:00", "¥ 4,950,000"),
    ("broken", "2026 年信息化服务采购公告", "", "朝阳区", "2026-08-29T16:02:00+08:00", "未披露"),
]


@router.get("/tenders", response_class=HTMLResponse)
def tender_list(page: int = 1) -> str:
    start = (max(page, 1) - 1) * 2
    rows = NOTICES[start : start + 2]
    items = "".join(
        f'<li data-id="{code}"><a class="notice-title" href="/demo/tenders/{code}">{title}</a>'
        f'<time datetime="{published}">{published[:10]}</time></li>'
        for code, title, _buyer, _region, published, _budget in rows
    )
    next_link = f'<a class="pagination-next" href="/demo/tenders?page={page + 1}">下一页</a>' if start + 2 < len(NOTICES) else ""
    return f"""<!doctype html><html lang="zh-CN"><head><title>Extrio 真实采集演示源</title></head>
    <body><main><h1>北京市公共资源交易公告</h1><ul class="notice-list">{items}</ul>{next_link}</main></body></html>"""


@router.get("/tenders/{code}", response_class=HTMLResponse)
def tender_detail(code: str) -> str:
    notice = next((row for row in NOTICES if row[0] == code), None)
    if notice is None:
        return "<h1>Not found</h1>"
    _code, title, buyer, region, published, budget = notice
    buyer_html = f'<span data-field="buyer">{buyer}</span>' if buyer else ""
    return f"""<!doctype html><html lang="zh-CN"><head><title>{title}</title></head><body>
    <article class="notice"><h1 class="notice-title">{title}</h1><div class="meta">{buyer_html}
    <span data-field="region">{region}</span><time datetime="{published}">{published[:10]}</time></div>
    <p class="notice-budget">预算：<span class="amount">{budget}</span></p>
    <div class="notice-content">这是用于验证 Extrio Crawl4AI 探索与 Crawlee 运行闭环的可重复公开页面。</div></article></body></html>"""
