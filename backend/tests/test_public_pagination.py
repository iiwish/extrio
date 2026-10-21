import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from extrio.contracts import ContractBundle
from extrio.harvest import discover_records_from_spec
from extrio.public_pagination import hospital_list_request, hospital_paging_script, validate_hospital_list, verified_empty_public_list

URL = 'https://www.zy91.com/general/list?right_cid=192&cid=193'
HTML = '<script src="/public/cn/js/pagedata.js"></script><script>pagedata(\'1680\',\'193\',\'pageBox\',\'list\',\'articles\',10)</script>'
JS = ("function loadData(page,cid,pageBox,listtype,pagesize){$.ajax({url: '/content/get_article', "
      "data: {page:page,cid:cid,cur:pagesize}, method: 'get'}); var url = '/content/default/';}")
API = 'https://www.zy91.com/content/get_article?page=1&cid=193&cur=10'


def test_hospital_endpoint_requires_exact_publisher_config_and_script():
    assert hospital_paging_script(HTML, URL) == 'https://www.zy91.com/public/cn/js/pagedata.js'
    assert hospital_list_request(HTML, URL, JS) == API
    assert hospital_paging_script(HTML, URL.replace('www.zy91.com', 'evil.test')) is None
    assert hospital_paging_script(HTML.replace('193', '194'), URL) is None
    assert hospital_paging_script(HTML.replace('/public/cn/js/', 'https://evil.test/'), URL) is None
    assert hospital_list_request(HTML, URL, JS.replace("'get'", "'post'")) is None


@pytest.mark.parametrize('row', [{'id': '../1', 'category_id': 193}, {'id': 1, 'category_id': 194}])
def test_hospital_response_rejects_wrong_category_or_unsafe_id(row):
    with pytest.raises(ValueError):
        validate_hospital_list(API, json.dumps({'code': 1, 'data': {'list': [row]}}))


def test_only_validated_publisher_json_can_prove_an_empty_list():
    empty = json.dumps({'code': 1, 'data': {'list': []}})
    assert verified_empty_public_list(API, empty)
    assert not verified_empty_public_list('https://example.com/list', empty)
    with pytest.raises(ValueError):
        verified_empty_public_list(API, json.dumps({'code': 0, 'data': {'list': []}}))


def test_numeric_path_transform_builds_same_host_urls_and_matches_evidence():
    response = json.dumps({'data': {'list': [{'id': 42, 'title': 'Notice'}]}})
    spec = {'itemsSelector': 'jsonpath:$.data.list[*]', 'fields': {
        'detailUrl': {'selector': 'jsonpath:$.id', 'transforms': [{'type': 'url_path', 'prefix': '/content/default/193/'}]},
    }, 'pagination': {'type': 'page'}}
    records, _ = discover_records_from_spec(response, API, spec)
    assert records == [{'detailUrl': 'https://www.zy91.com/content/default/193/42'}]
    for unsafe in ['../2', '//evil.test/x', '42?token=x', '', True]:
        response = json.dumps({'data': {'list': [{'id': unsafe}]}})
        assert discover_records_from_spec(response, API, spec)[0] == []


@pytest.mark.parametrize('prefix', ['//evil.test/', '/a/../', '/a/?token=', '/a/#', 'https://evil.test/', '/a/{{id}}/'])
def test_numeric_url_path_schema_rejects_dynamic_or_cross_host_prefixes(prefix):
    contracts = ContractBundle(Path(__file__).resolve().parents[2] / 'docs/contracts')
    for schema in (contracts.rule_plan_schema, contracts.gather_schema):
        definition = schema['$defs']['urlPathTransform']
        with pytest.raises(ValidationError):
            Draft202012Validator(definition).validate({'type': 'url_path', 'prefix': prefix})
