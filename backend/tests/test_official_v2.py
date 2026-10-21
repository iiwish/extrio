import json
from types import SimpleNamespace

import pytest
from test_official_documents import ORIGINAL, TITLE, XMU, original, resolver
from test_official_documents import public_dns as public_dns

from extrio.official_documents import OfficialDocuments
from extrio.pdf_document import extract


@pytest.mark.parametrize('version', ['official_notice_v1', 'official_notice_v2'])
async def test_repost_dates_require_explicit_new_profile(public_dns, version):
    landing = f'<div class="ctitle"><h1>{TITLE}</h1><div class="info"><i>2026-10-16</i></div></div>'
    landing += f'<div class="ccontent">公告原文：<a href="{ORIGINAL}">中国政府采购网</a></div>'
    r, _, _ = resolver(XMU, {('ztb.xmu.edu.cn', '/cghw/837.chtml'): (200, {}, landing),
                             ('www.ccgp.gov.cn', ORIGINAL.split('www.ccgp.gov.cn')[1]): (200, {}, original())})
    r.profile = version
    value = json.loads(await r.resolve({'detailUrl': 'https://ztb.xmu.edu.cn/cghw/837.chtml', 'listTitle': TITLE}, 1))
    assert bool(value['content']) == (version == 'official_notice_v2')
    if version.endswith('v2'):
        assert value['publishedAt'] == '2026-10-15'
        assert value['resolution']['publisherPublishedAt'] == '2026-10-16'
        assert value['resolution']['originalPublishedAt'] == '2026-10-15'


@pytest.mark.parametrize('wrong', [None, 'buyer', 'project', 'round', 'stage'])
async def test_original_metadata_identity_is_constrained(public_dns, wrong):
    title = '厦门大学宿舍空调采购招标公告(第二次)'
    project = '厦门大学宿舍空调采购' if wrong != 'project' else '厦门大学宿舍家具采购'
    full = project + ('首次公开招标公告' if wrong == 'round' else '（二次）公开招标公告')
    html = original(full).replace('厦门大学测试设备</td>', project + '</td>')
    if wrong == 'buyer':
        html = html.replace('<td>厦门大学</td>', '<td>其他大学</td>')
    url = ORIGINAL.replace('/gkzb/', '/cjgg/') if wrong == 'stage' else ORIGINAL
    r = OfficialDocuments.__new__(OfficialDocuments)
    r.host, r.profile = 'ztb.xmu.edu.cn', 'official_notice_v2'
    value = {'resolution': {}}
    if wrong:
        with pytest.raises(ValueError):
            await r.original(value, url, html, title, '2026-10-15')
    else:
        await r.original(value, url, html, title, '2026-10-15')
        assert value['content'] and value['resolution']['identityMethod'] == 'publisher_link_buyer_exact_project'


@pytest.mark.parametrize(('title', 'project'), [
    ('复旦大学聚合物定量分析三重四级杆液质联用仪国际公开招标公告', '聚合物定量分析三重四级杆液质联用仪'),
    ('复旦大学分子束外延设备采购项目招标公告', '复旦大学分子束外延设备采购项目'),
    ('复旦大学海洋浮标采购（第二次）公开招标公告', '复旦大学海洋浮标采购'),
    ('复旦大学消磁器国际招标公告', '复旦大学消磁器'),
])
async def test_identical_publisher_and_original_titles_remain_valid(public_dns, title, project):
    html = original(title).replace('<td>厦门大学</td>', '<td>复旦大学</td>').replace('厦门大学测试设备</td>', project + '</td>')
    r = OfficialDocuments.__new__(OfficialDocuments)
    r.host, r.profile = 'czzx.fudan.edu.cn', 'official_notice_v2'
    value = {'resolution': {}}
    await r.original(value, ORIGINAL, html, title, '2026-10-15')
    assert value['content']


@pytest.mark.parametrize('large_image', [False, True])
def test_known_footer_relief_cannot_hide_a_scanned_body(monkeypatch, large_image):
    footer = ('主办单位：中华人民共和国财政部国库司 网站标识码：bm14000002 '
              '京ICP备19054529号-1 京公网安备11010602060068号 中华人民共和国财政部 版权所有 联系我们 意见反馈')

    class Page(dict):
        mediabox = SimpleNamespace(width=600, height=800)

        def extract_text(self, **kwargs):
            if self.get('footer'):
                if visit := kwargs.get('visitor_operand_before'):
                    visit(b'Do', ['/Logo'], [600 if large_image else 40, 0, 0, 700 if large_image else 40, 0, 0], [])
                return footer
            return 'Complete body text ' * 30

    class Obj(dict):
        def get_object(self):
            return self

    body = Page()
    last = Page(footer=True)
    last['/Resources'] = Obj({'/XObject': Obj({'/Logo': Obj({'/Subtype': '/Image'})})})
    monkeypatch.setattr('pypdf.PdfReader', lambda *_a, **_k: SimpleNamespace(is_encrypted=False, pages=[body, last]))
    if large_image:
        with pytest.raises(ValueError, match='requires_review'):
            extract(b'%PDF-fixture', allow_footer=True)
    else:
        assert extract(b'%PDF-fixture', allow_footer=True)['footerPages'] == [2]
