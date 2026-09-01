from pathlib import Path

from jsonschema import Draft202012Validator

from extrio.contracts import ContractBundle
from extrio.harvest import (
    build_candidate,
    build_candidate_from_plan,
    build_gather_spec,
    contract_field_values,
    discover_records_from_spec,
    make_item,
)

ROOT = Path(__file__).resolve().parents[2]


def collector() -> dict:
    return {
        "id": "collector_demo",
        "name": "Demo",
        "intent": "Collect tenders",
        "sourceUrl": "http://127.0.0.1:8000/demo/tenders",
        "sourceHost": "127.0.0.1",
        "collectionVersion": "tender_notice_v4",
    }


def test_rule_plan_schema_is_valid_draft_2020_12() -> None:
    contracts = ContractBundle(ROOT / "docs/contracts")
    Draft202012Validator.check_schema(contracts.rule_plan_schema)


def test_generated_gather_spec_validates_against_frozen_schema() -> None:
    contracts = ContractBundle(ROOT / "docs/contracts")
    spec = build_gather_spec(collector(), contracts)
    contracts.validate_gather_spec(spec)
    assert spec["schemaVersion"] == "extrio.gather.v1"
    assert spec["collect"]["detail"]["fields"]["buyer"]["required"] is True


def test_llm_rule_plan_compiles_arbitrary_site_structure_without_profile() -> None:
    contracts = ContractBundle(ROOT / "docs/contracts")
    current = {**collector(), "intent": "采集项目名称、采购单位、金额、发布日期和正文"}
    list_html = """
      <section id="results">
        <div class="result-row"><a class="subject" href="/records/42">通用项目 A</a><b data-date>2026-09-01</b></div>
      </section>
      <a rel="next" href="?cursor=next">下一页</a>
    """
    detail_url = "http://127.0.0.1:8000/records/42"
    detail_html = """
      <main data-record><h2>通用项目 A</h2><span class="agency">通用采购人</span>
      <data value="880000">88 万元</data><time datetime="2026-09-01"></time><article>这里是正文</article></main>
    """
    plan = {
        "schemaVersion": "extrio.rule-plan.v1",
        "mode": "list_detail",
        "transport": "http",
        "list": {
            "responseType": "html",
            "itemsSelector": "css:#results .result-row",
            "fields": {
                "listTitle": {
                    "label": "列表标题",
                    "selector": "css:a.subject::text",
                    "valueType": "string",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim", "collapse_whitespace"],
                },
                "listPublishedAt": {
                    "label": "列表日期",
                    "selector": "css:[data-date]::text",
                    "valueType": "string",
                    "required": False,
                    "onError": "null",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim"],
                },
                "detailUrl": {
                    "label": "详情链接",
                    "selector": "css:a.subject::attr(href)",
                    "valueType": "url",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim", "absolute_url"],
                },
            },
            "pagination": {
                "type": "next_link",
                "selector": "css:a[rel=next]",
                "maxPages": 50,
                "allowCrossHost": False,
            },
        },
        "detail": {
            "responseType": "html",
            "fields": {
                "projectName": {
                    "label": "项目名称",
                    "selector": "css:main[data-record] h2::text",
                    "valueType": "string",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim", "collapse_whitespace"],
                },
                "agencyName": {
                    "label": "采购单位",
                    "selector": "css:.agency::text",
                    "valueType": "string",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim"],
                },
                "amount": {
                    "label": "金额",
                    "selector": "css:data::attr(value)",
                    "valueType": "number",
                    "required": False,
                    "onError": "null",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim"],
                },
                "publishedAt": {
                    "label": "发布日期",
                    "selector": "css:time::attr(datetime)",
                    "valueType": "datetime",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim"],
                    "datetimeFormat": "ISO8601_DATE",
                    "defaultTimezone": "Asia/Shanghai",
                },
                "body": {
                    "label": "正文",
                    "selector": "css:article::text",
                    "valueType": "string",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim", "collapse_whitespace"],
                },
            },
        },
        "bindings": {
            "detailUrl": "list.detailUrl",
            "listTitle": "list.listTitle",
            "listPublishedAt": "list.listPublishedAt",
            "title": "detail.projectName",
            "publishedAt": "detail.publishedAt",
            "content": "detail.body",
        },
        "identityFields": ["detailUrl"],
        "fingerprintFields": ["projectName", "agencyName", "amount", "publishedAt", "body"],
        "rationale": "列表发现详情链接，详情页形成规范化记录。",
    }

    contracts.validate_rule_plan(plan)
    candidate = build_candidate_from_plan(current, contracts, plan, list_html, [(detail_url, detail_html)])
    item = make_item(
        {**current, "candidate": candidate},
        {"id": "run_generic", "ruleVersion": "rule_generic_v1"},
        detail_url,
        detail_html,
        1,
        source_record={"listTitle": "通用项目 A", "detailUrl": detail_url},
    )

    assert candidate["listSelector"] == "css:#results .result-row"
    assert candidate["gatherSpec"]["compiler"]["agent"]["model"] == "pending-model"
    assert item["decision"] == "accepted"
    assert item["title"] == "通用项目 A"
    assert item["extractedData"] == {
        "listTitle": "通用项目 A",
        "detailUrl": detail_url,
        "projectName": "通用项目 A",
        "agencyName": "通用采购人",
        "amount": 880000.0,
        "publishedAt": "2026-09-01",
        "body": "这里是正文",
    }


def test_required_list_field_is_enforced_when_detail_is_built() -> None:
    contracts = ContractBundle(ROOT / "docs/contracts")
    current = collector()
    candidate = build_candidate_from_plan(
        current,
        contracts,
        {
            "schemaVersion": "extrio.rule-plan.v1",
            "mode": "list_detail",
            "transport": "http",
            "list": {
                "responseType": "html",
                "itemsSelector": "css:li",
                "fields": {
                    "listTitle": {
                        "label": "标题",
                        "selector": "css:a::text",
                        "valueType": "string",
                        "required": True,
                        "onError": "reject_item",
                        "multipleMatchPolicy": "first",
                        "transforms": ["trim"],
                    },
                    "detailUrl": {
                        "label": "详情",
                        "selector": "css:a::attr(href)",
                        "valueType": "url",
                        "required": True,
                        "onError": "reject_item",
                        "multipleMatchPolicy": "first",
                        "transforms": ["absolute_url"],
                    },
                },
                "pagination": {"type": "none"},
            },
            "detail": {
                "responseType": "html",
                "fields": {
                    "title": {
                        "label": "标题",
                        "selector": "css:h1::text",
                        "valueType": "string",
                        "required": True,
                        "onError": "reject_item",
                        "multipleMatchPolicy": "first",
                        "transforms": ["trim"],
                    }
                },
            },
            "bindings": {"detailUrl": "list.detailUrl", "title": "detail.title"},
            "identityFields": ["detailUrl"],
            "fingerprintFields": ["title"],
            "rationale": "测试列表质量门。",
        },
        '<li><a href="/detail/1">A</a></li>',
        [("http://127.0.0.1:8000/detail/1", "<h1>A</h1>")],
    )
    item = make_item(
        {**current, "candidate": candidate},
        {"id": "run_required_list", "ruleVersion": "rule_v1"},
        "http://127.0.0.1:8000/detail/1",
        "<h1>A</h1>",
        1,
        source_record={"listTitle": "", "detailUrl": "http://127.0.0.1:8000/detail/1"},
    )

    assert item["decision"] == "rejected"
    assert item["rejectionReason"] == "必填字段 listTitle 未通过非空质量门"


def test_deterministic_extractor_executes_jsonpath_rules() -> None:
    payload = '{"records":[{"name":"项目 A","href":"/records/42","amount":"1,200.50"}],"next":"/api?page=2"}'
    list_spec = {
        "itemsSelector": "jsonpath:$.records[*]",
        "fields": {
            "listTitle": {"selector": "jsonpath:$.name", "multipleMatchPolicy": "first", "transforms": ["trim"]},
            "detailUrl": {
                "selector": "jsonpath:$.href",
                "multipleMatchPolicy": "first",
                "transforms": ["trim", "absolute_url"],
            },
        },
        "pagination": {"type": "next_link", "selector": "jsonpath:$.next", "maxPages": 10, "allowCrossHost": False},
    }

    records, next_url = discover_records_from_spec(payload, "https://example.com/api?page=1", list_spec)
    values = contract_field_values(
        payload,
        "https://example.com/api?page=1",
        {
            "amount": {
                "selector": "jsonpath:$.records[0].amount",
                "valueType": "number",
                "multipleMatchPolicy": "first",
                "transforms": ["trim"],
            }
        },
    )

    assert records == [{"listTitle": "项目 A", "detailUrl": "https://example.com/records/42"}]
    assert next_url == "https://example.com/api?page=2"
    assert values == {"amount": 1200.5}


def test_candidate_and_rejected_item_preserve_machine_semantics() -> None:
    contracts = ContractBundle(ROOT / "docs/contracts")
    list_html = '<ul class="notice-list"><li><a class="notice-title" href="/detail/1">A</a></li></ul>'
    detail_html = (
        '<h1 class="notice-title">A</h1><div class="meta"><span data-field="region">北京</span>'
        '<time datetime="2026-08-30T00:00:00Z"></time></div>'
    )
    candidate = build_candidate(collector(), contracts, list_html, [("http://127.0.0.1:8000/detail/1", detail_html)])
    item = make_item(
        {**collector(), "candidate": candidate},
        {"id": "run_demo", "ruleVersion": "rule_v1"},
        "http://127.0.0.1:8000/detail/1",
        detail_html,
        1,
    )
    assert candidate["mode"] == "list_detail"
    assert item["decision"] == "rejected"
    assert item["revision"] is None
    assert item["lineage"]["observationId"] is None


def test_compiles_beijing_procurement_intention_structure() -> None:
    contracts = ContractBundle(ROOT / "docs/contracts")
    source_url = "http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_1.htm"
    current = {**collector(), "sourceUrl": source_url, "sourceHost": "www.ccgp-beijing.gov.cn"}
    list_html = """
        <ul class="inner-ul">
          <li><a href="//www.ccgp-beijing.gov.cn/yxgk/sjcgyx/2026/8/example.htm">采购意向</a></li>
        </ul>
        <div class="fenye_ul">
          <li><a href="javascript:void(0)">1</a></li>
          <li><a href="//www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_2.htm">下一页</a></li>
          <li><a href="//www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_143.htm">尾页</a></li>
          <li>跳页</li>
        </div>
    """
    detail_url = "http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/2026/8/example.htm"
    list_title = "北京市规划和自然资源委员会2026年8至12月政府采购意向"
    detail_html = f"""
        <div class="xl-box-t"><h1><p>{list_title}</p></h1><span>2026-08-28</span></div>
        <div id="BodyLabel"><table><tbody><tr>
          <td>1</td><td>北京市规划和自然资源委员会</td><td>政务云租用</td>
          <td>采购需求</td><td>2400</td><td>2026-10</td><td></td>
        </tr></tbody></table></div>
    """

    candidate = build_candidate(current, contracts, list_html, [(detail_url, detail_html)])
    runtime_html = detail_html.replace(f"<h1><p>{list_title}</p></h1>", f"<h1></h1><p>{list_title}</p>")
    item = make_item(
        {**current, "candidate": candidate},
        {"id": "run_ccgp", "ruleVersion": "rule_ccgp_v1"},
        detail_url,
        runtime_html,
        1,
        source_record={"listTitle": list_title, "listPublishedAt": "2026-08-28", "detailUrl": detail_url},
    )

    assert candidate["mode"] == "list_detail"
    assert candidate["listSelector"] == "css:.inner-ul > li"
    assert candidate["detailLinkSelector"] == "css:a[href]"
    assert candidate["pagination"]["selector"] == "css:.fenye_ul > li:nth-last-of-type(3) > a"
    assert candidate["gatherSpec"]["collect"]["list"]["fields"]["listTitle"]["selector"] == "css:a[href]::text"
    assert candidate["gatherSpec"]["collect"]["list"]["fields"]["listPublishedAt"]["selector"] == "css:.datetime::text"
    assert candidate["gatherSpec"]["collect"]["budget"]["maxItems"] == 300
    assert item["decision"] == "accepted"
    assert item["listTitle"] == list_title
    assert item["title"] == list_title
    assert item["publishedAt"] == "2026-08-28"
    assert "政务云租用" in item["content"]
    assert item["observedAt"]


def test_compiles_procurement_table_with_header_inside_tbody() -> None:
    contracts = ContractBundle(ROOT / "docs/contracts")
    source_url = "http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_1.htm"
    current = {**collector(), "sourceUrl": source_url, "sourceHost": "www.ccgp-beijing.gov.cn"}
    list_html = """
        <ul class="inner-ul"><li><a href="/detail/header-in-body.htm">采购意向</a></li></ul>
        <div class="fenye_ul"><li>首页</li><li>上一页</li><li><a href="/page-2">下一页</a></li><li>尾页</li><li>跳页</li></div>
    """
    detail_url = "http://www.ccgp-beijing.gov.cn/detail/header-in-body.htm"
    list_title = "首都博物馆2026年1至12月政府采购意向"
    detail_html = f"""
        <div class="xl-box-t"><h1><p>{list_title}</p></h1><span>2026-08-27</span></div>
        <div id="BodyLabel"><table><tbody>
          <tr><th>序号</th><th>预算单位名称</th><th>采购项目名称</th><th>需求</th><th>预算</th><th>预计采购时间</th></tr>
          <tr><td>1</td><td>首都博物馆</td><td>物业综合服务</td><td>服务需求</td><td>2400</td><td>2026-12</td></tr>
        </tbody></table></div>
    """

    candidate = build_candidate(current, contracts, list_html, [(detail_url, detail_html)])
    item = make_item(
        {**current, "candidate": candidate},
        {"id": "run_ccgp_header", "ruleVersion": "rule_ccgp_v1"},
        detail_url,
        detail_html,
        1,
        source_record={"listTitle": list_title, "listPublishedAt": "2026-08-27", "detailUrl": detail_url},
    )

    assert item["decision"] == "accepted"
    assert item["title"] == list_title
    assert item["publishedAt"] == "2026-08-27"
    assert "物业综合服务" in item["content"]
