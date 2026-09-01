from extrio.model_gateway import _dom_evidence, _json_content, normalize_discovery_plan, normalize_rule_plan


def test_json_content_accepts_compact_and_fenced_responses() -> None:
    assert _json_content('{"approved":true}') == {"approved": True}
    assert _json_content('```json\n{"approved": false, "reason": "missing"}\n```')["reason"] == "missing"


def test_dom_evidence_removes_active_content_but_keeps_structure_and_text() -> None:
    evidence = _dom_evidence(
        '<html><script>ignore()</script><style>.x{}</style><main id="records"><a class="title" href="/42">项目 A</a></main></html>'
    )

    assert "ignore" not in evidence
    assert "<style" not in evidence
    assert 'id="records"' in evidence
    assert 'class="title"' in evidence
    assert "项目 A" in evidence


def test_discovery_plan_is_normalized_to_the_deterministic_selector_dialect() -> None:
    plan = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "transport": "browser",
            "list": {
                "responseType": "html",
                "itemsSelector": ".records > article",
                "fields": {
                    "listTitle": {"selector": "h2::text", "required": True},
                    "detailUrl": {"selector": "a::attr(href)", "required": True},
                },
                "pagination": {"type": "next_link", "selector": "a.next", "maxPages": 25},
            },
        }
    )

    assert plan["list"]["itemsSelector"] == "css:.records > article"
    assert plan["list"]["fields"]["detailUrl"]["selector"] == "css:a::attr(href)"
    assert plan["list"]["fields"]["detailUrl"]["transforms"] == ["trim", "absolute_url"]
    assert plan["list"]["pagination"] == {
        "type": "next_link",
        "selector": "css:a.next",
        "maxPages": 25,
        "allowCrossHost": False,
    }


def test_html_field_rules_gain_deterministic_value_accessors() -> None:
    plan = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "list": {
                "responseType": "html",
                "itemsSelector": "li.notice",
                "fields": {
                    "title": {"selector": "a.title", "required": True},
                    "detailUrl": {"selector": "a.title", "valueType": "url", "required": True},
                },
                "pagination": {"type": "none"},
            },
        }
    )

    assert plan["list"]["fields"]["title"]["selector"] == "css:a.title::text"
    assert plan["list"]["fields"]["detailUrl"]["selector"] == "css:a.title::attr(href)"


def test_final_plan_keeps_proven_pagination_when_model_suggests_unsupported_pattern() -> None:
    discovery = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "list": {
                "responseType": "html",
                "itemsSelector": "li.notice",
                "fields": {"detailUrl": {"selector": "a::attr(href)", "required": True}},
                "pagination": {"type": "none"},
            },
        }
    )

    plan = normalize_rule_plan(
        {
            "list": {"pagination": {"type": "numbered_url_pattern", "template": "index_{page}.htm"}},
            "detail": {
                "responseType": "html",
                "fields": {"title": {"selector": "h1::text", "required": True}},
            },
            "identityFields": ["detailUrl"],
            "fingerprintFields": ["title"],
        },
        discovery,
    )

    assert plan["list"]["pagination"] == {"type": "none"}


def test_final_plan_keeps_proven_browser_transport() -> None:
    discovery = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "transport": "browser",
            "list": {
                "responseType": "html",
                "itemsSelector": "li.notice",
                "fields": {"detailUrl": {"selector": "a::attr(href)", "required": True}},
                "pagination": {"type": "none"},
            },
        }
    )

    plan = normalize_rule_plan(
        {
            "transport": "http",
            "detail": {"responseType": "html", "fields": {"title": {"selector": "h1::text"}}},
            "identityFields": ["detailUrl"],
            "fingerprintFields": ["title"],
        },
        discovery,
    )

    assert plan["transport"] == "browser"
