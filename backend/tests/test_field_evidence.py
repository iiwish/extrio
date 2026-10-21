import json

import pytest

from extrio.harvest import field_evidence, publisher_truncated_title_match


def spec():
    return {
        'sourceContext': {'entrypoints': ['https://example.com/list']},
        'collect': {
            'list': {'itemsSelector': 'css:ul.records > li', 'fields': {
                'listTitle': {'selector': 'css:a::text'},
                'detailUrl': {'selector': 'css:a::attr(href)'},
            }},
            'detail': {'fields': {'title': {'selector': 'css:h1::text'}}},
        },
        'contract': {'fieldBindings': {'listTitle': 'list.listTitle', 'detailUrl': 'list.detailUrl', 'title': 'detail.title'}},
    }


LIST = '<a href="/nav">Navigation</a><ul class="records"><li><a href="/a">A</a></li><li><a href="/b">B</a></li></ul>'


@pytest.mark.parametrize('key', ['listTitle', 'detailUrl'])
def test_list_evidence_matches_detail_url_not_first_anchor_or_row(key):
    proof = field_evidence(spec(), key, LIST, 'https://example.com/b', '<h1>B</h1>')
    assert 'href="/b"' in proof
    assert '/nav' not in proof and 'href="/a"' not in proof


def test_detail_evidence_uses_detail_document():
    assert field_evidence(spec(), 'title', LIST, 'https://example.com/b', '<h1>B</h1>') == '<h1>B</h1>'


def test_unmatched_row_does_not_fall_back_to_navigation_or_other_record():
    proof = field_evidence(spec(), 'detailUrl', LIST, 'https://example.com/missing', '<a href="/wrong">Wrong</a>')
    assert '<a' not in proof


def test_json_evidence_is_the_matching_record_and_is_not_claimed_as_dom():
    value = spec()
    value['collect']['list']['itemsSelector'] = 'jsonpath:$.rows[*]'
    value['collect']['list']['fields'] = {
        'listTitle': {'selector': 'jsonpath:$.title'},
        'detailUrl': {'selector': 'jsonpath:$.url', 'transforms': ['absolute_url']},
    }
    response = json.dumps({'rows': [{'title': 'A', 'url': '/a'}, {'title': 'B', 'url': '/b'}]})
    proof = field_evidence(value, 'listTitle', response, 'https://example.com/b', '<h1>B</h1>')
    assert 'JSON' in proof and 'B' in proof and 'A' not in proof


def test_single_document_evidence_uses_document_not_an_item_row():
    value = spec()
    del value['collect']['detail']
    value['collect']['list']['fields']['title'] = {'selector': 'css:h1::text'}
    value['contract']['fieldBindings'] = {}
    assert field_evidence(value, 'title', '<h1>Single</h1>', 'https://example.com/list', '') == '<h1>Single</h1>'


@pytest.mark.parametrize('variation', ['valid', 'host', 'short', 'date', 'breadcrumb', 'url', 'prefix'])
def test_truncated_csg_title_requires_long_prefix_same_url_date_and_breadcrumb(variation):
    title = 'Verified procurement project ' * 4 + 'award notice'
    shown = title[:80] + '...'
    url = 'http://www.bidding.csg.cn/zbhxrgs/123.jhtml'
    record = {'detailUrl': url, 'publishedAt': '2026-10-19'}
    html = '<div class="W1200 Center Top18">Home &gt; ' + title + '</div>'
    if variation == 'host':
        url = url.replace('www.bidding.csg.cn', 'evil.test')
    if variation == 'short':
        shown = title[:10] + '...'
    if variation == 'date':
        record['publishedAt'] = '2026-10-18'
    if variation == 'breadcrumb':
        html = html.replace(title, 'Wrong project')
    if variation == 'url':
        record['detailUrl'] += 'x'
    if variation == 'prefix':
        shown = 'Different procurement project ' * 3 + '...'
    assert publisher_truncated_title_match(url, html, title, shown, '发布时间：2026-10-19 12:00:00', record) == (variation == 'valid')
