import json
from unittest.mock import AsyncMock

import pytest
from test_official_documents import public_dns as public_dns
from test_official_documents import resolver

from extrio.official_documents import resolved_title_matches


@pytest.mark.parametrize('case', ['valid', 'v1', 'v2', 'guid', 'scope', 'temporary', 'type', 'frame', 'endpoint', 'title', 'query'])
async def test_comparison_procurement_requires_signed_exact_public_template(public_dns, monkeypatch, case):
    guid = '09922b06-6f58-4e2f-9e0c-3f035009a7d4'
    name = '广东医院后勤保障物资采购长期供货商项目'
    root = '/gdjd-xunjia/gonggaoxinxi/'
    frame = 'jieGuo_view.html' if case == 'frame' else 'gongGao_view.html'
    template = root + 'queryXiangMuByGuid.do?guid= /gdjd-xunjia/buyi/queryBuYiPagination.do?xiangMuGuid='
    if case == 'endpoint':
        template = template.replace('queryXiangMuByGuid', 'unapprovedRead')
    data = {'xiangMuGuid': 'bad' if case == 'guid' else guid, 'xiangMuName': name,
            'gongKaiType': 51 if case == 'scope' else 10, 'isTempGongGao': case == 'temporary',
            'caiGouType': 3 if case == 'type' else 5, 'gongGaoStartTimeText': '2026-10-15 20:10:00'}
    pages = {('eps.gdebidding.com', '/gg/cmsGGDetailcg'): (200, {},
              f'<iframe id="iframepage" src="{root}{frame}?guid={guid}"></iframe>'),
             ('eps.gdebidding.com', root + frame): (200, {}, template),
             ('eps.gdebidding.com', root + 'queryXiangMuByGuid.do'): (200, {}, json.dumps(data)),
             ('eps.gdebidding.com', '/gdjd-xunjia/common/getSystemTime.do'): (200, {}, '2026-10-19'),
             ('eps.gdebidding.com', '/gdjd-xunjia/buyi/queryBuYiPagination.do'): (200, {}, '{"total":0,"rows":[]}')}
    r, _, calls = resolver('http://www.gdebidding.com/cgxx/index.jhtml', pages)
    r.profile = {'v1': 'official_notice_v1', 'v2': 'official_notice_v2'}.get(case, 'official_notice_v3')
    r.render_blocked = []
    rendered_title = '其他项目公告' if case == 'title' else name + '公告'
    monkeypatch.setattr(r, 'render_eps', AsyncMock(return_value=(rendered_title + '\n' + '采购项目公开正文。' * 30, '<html/>')))
    url = f'https://eps.gdebidding.com/gg/cmsGGDetailcg?guid={guid}&pageName=xbcg'
    if case == 'query':
        url += '&guid=other'
    record = {'detailUrl': url, 'listTitle': name}
    result = json.loads(await r.resolve(record, 1))
    if case == 'valid':
        assert not result['resolution']['error'] and result['content']
        assert result['publishedAt'] == '2026-10-15'
        assert result['resolution']['procurementType'] == 'comparison'
        assert resolved_title_matches(url, result, record)
        assert not resolved_title_matches(url, result, {**record, 'listTitle': name + '成交结果公告'})
    else:
        assert result['resolution']['error'] and not result['content']
    assert all(method == 'GET' for method, _, _ in calls)
