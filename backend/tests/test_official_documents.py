import io
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from extrio.official_documents import OfficialDocuments, profile_hosts, validate_resolution
from extrio.pdf_document import extract
from extrio.source_network import SourceNetwork, SourceNetworkError

XMU = 'https://ztb.xmu.edu.cn/cghw/index.chtml'
ORIGINAL = 'https://www.ccgp.gov.cn/cggg/zygg/gkzb/202610/t20261015_27500601.htm'
TITLE = '厦门大学测试设备采购信息'
FULL = '厦门大学测试设备公开招标公告'


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *_a, **_k: [(2, 1, 6, '', ('93.184.216.34', 443))])


def resolver(entry, pages):
    saved = {}
    calls = []

    def respond(request):
        calls.append((request.method, request.headers['host'], request.url.path))
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        status, headers, body = pages[(request.headers['host'], request.url.path)]
        return httpx.Response(status, headers=headers, content=body)

    network = SourceNetwork(profile_hosts(entry), transport=httpx.MockTransport(respond), upgrade_fudan_original=True)
    return OfficialDocuments(network, entry, saved.__setitem__), saved, calls


def original(title=FULL, date='2026-10-15'):
    return f'''<meta name="ArticleTitle" content="{title}"><meta name="PubDate" content="{date}">
    <div class="table"><table><tr><td class="title">采购单位</td><td>厦门大学</td></tr>
    <tr><td class="title">采购项目名称</td><td>厦门大学测试设备</td></tr></table></div>
    <div class="vF_detail_content">{'Actual official notice body. ' * 20}</div>'''


@pytest.mark.parametrize('host', ['czzx.fudan.edu.cn', 'ztb.xmu.edu.cn', 'www.gdebidding.com', 'evil.test'])
def test_profiles_have_exact_hosts_only(host):
    hosts = profile_hosts('https://' + host + '/list')
    assert host in hosts and len(hosts) == (1 if host == 'evil.test' else 2)
    assert not any('*' in h for h in hosts)


@pytest.mark.parametrize('bad', ['hosts', 'source', 'transport', 'fields', None])
def test_signed_resolution_scope(bad):
    spec = {'sourceContext': {'entrypoints': [XMU], 'allowedHosts': sorted(profile_hosts(XMU))},
            'collect': {'detail': {'resolution': 'official_notice_v1', 'transport': 'http', 'responseType': 'json',
                                   'fields': {'content': {'selector': 'jsonpath:$.content'}}}}}
    if bad == 'hosts':
        spec['sourceContext']['allowedHosts'].append('evil.test')
    if bad == 'source':
        spec['sourceContext']['entrypoints'] = ['https://evil.test/list']
    if bad == 'transport':
        spec['collect']['detail']['transport'] = 'browser'
    if bad == 'fields':
        spec['collect']['detail']['fields']['content']['selector'] = 'css:body::text'
    if bad:
        with pytest.raises(SourceNetworkError):
            validate_resolution(spec)
    else:
        validate_resolution(spec)


@pytest.mark.parametrize('variation', ['valid', 'project', 'date', 'stage', 'external'])
async def test_publisher_linked_original_identity_and_date(public_dns, variation):
    target = ORIGINAL.replace('/gkzb/', '/gzgg/') if variation == 'stage' else ORIGINAL
    if variation == 'external':
        target = target.replace('www.ccgp.gov.cn', 'evil.test')
    landing = f'<div class="ctitle"><h1>{TITLE}</h1><div class="info"><i>2026-10-15</i></div></div>'
    landing += f'<div class="ccontent">采购信息原文详见：<a href="{target}">{target}</a></div>'
    pages = {('ztb.xmu.edu.cn', '/cghw/837.chtml'): (200, {}, landing),
             ('www.ccgp.gov.cn', target.split('www.ccgp.gov.cn')[-1]): (
                 200, {}, original('Other project' if variation == 'project' else FULL,
                                   '2026-10-16' if variation == 'date' else '2026-10-15'))}
    r, saved, calls = resolver(XMU, pages)
    result = json.loads(await r.resolve({'detailUrl': 'https://ztb.xmu.edu.cn/cghw/837.chtml', 'listTitle': TITLE}, 1))
    assert bool(result['content']) == (variation == 'valid')
    assert bool(result['resolution']['error']) == (variation != 'valid')
    assert all(method == 'GET' and host != 'evil.test' for method, host, _ in calls)
    assert saved


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('explicit_port', [False, True])
async def test_fudan_redirect_upgrade_never_sends_http_or_unapproved_host(public_dns, enabled, explicit_port):
    seen = []

    def respond(request):
        seen.append((request.url.scheme, request.headers['host']))
        if request.headers['host'] == 'czzx.fudan.edu.cn':
            target = ORIGINAL.replace('https:', 'http:')
            if explicit_port:
                target = target.replace('www.ccgp.gov.cn', 'www.ccgp.gov.cn:80')
            return httpx.Response(302, headers={'location': target})
        return httpx.Response(200, text='ok')

    n = SourceNetwork({'czzx.fudan.edu.cn', 'www.ccgp.gov.cn'}, transport=httpx.MockTransport(respond),
                      upgrade_fudan_original=enabled)
    if enabled:
        assert (await n.fetch('https://czzx.fudan.edu.cn/_redirect?x=1')).url == ORIGINAL
        assert n.redirect_evidence[0]['upgradedTo'] == ORIGINAL
    else:
        with pytest.raises(SourceNetworkError, match='redirect_https_downgrade'):
            await n.fetch('https://czzx.fudan.edu.cn/_redirect?x=1')
    assert all(scheme == 'https' for scheme, _ in seen)


@pytest.mark.parametrize('target', ['http://evil.test/notice', 'http://www.ccgp.gov.cn/admin', 'http://127.0.0.1/a'])
async def test_fudan_upgrade_does_not_allow_arbitrary_downgrades(public_dns, target):
    n = SourceNetwork({'czzx.fudan.edu.cn', 'www.ccgp.gov.cn'}, upgrade_fudan_original=True,
                      transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={'location': target})))
    with pytest.raises(SourceNetworkError, match='redirect_https_downgrade'):
        await n.fetch('https://czzx.fudan.edu.cn/_redirect?x=1')


def pdf_bytes(scanned=False, indirect=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=500)
    if not scanned:
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 50 450 Td (This is the full public procurement PDF document body for a test.) Tj ET')
        page[NameObject('/Contents')] = content
        if indirect:
            page[NameObject('/Resources')] = writer._add_object(page['/Resources'])
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_pdf_text_layer_and_scanned_quality_gate():
    assert extract(pdf_bytes())['pages'] == 1
    assert extract(pdf_bytes(indirect=True))['pages'] == 1
    with pytest.raises(ValueError, match='requires_review'):
        extract(pdf_bytes(scanned=True))
    with pytest.raises(ValueError, match='invalid_or_oversized'):
        extract(b'%PDF-' + b'x' * 5_000_000)


async def test_pdf_parser_isolated_subprocess():
    assert (await OfficialDocuments.pdf(pdf_bytes()))['extraction'] == 'text_layer'
    with pytest.raises(ValueError, match='requires_review'):
        await OfficialDocuments.pdf(pdf_bytes(scanned=True))


@pytest.mark.parametrize('variation', ['guid', 'private', 'deleted', 'frame_guid'])
async def test_eps_rejects_wrong_guid_or_nonpublic_data_before_render(public_dns, variation, monkeypatch):
    entry = 'http://www.gdebidding.com/cgxx/index.jhtml'
    guid = '90d51d70-d49e-4c9b-b0f0-075f1fd903a7'
    frame_guid = guid.replace('90d51', '00d51') if variation == 'frame_guid' else guid
    root = '/gdjd-xunjia/gonggaoxinxi/'
    landing = f'<iframe id="iframepage" src="{root}jieGuo_view.html?guid={frame_guid}"></iframe>'
    data = {'jieGuoGuid': guid if variation != 'guid' else 'wrong', 'hideForBidder': variation == 'private',
            'isGongKai': True, 'isDeleted': variation == 'deleted', 'xiangMu': {'xiangMuName': 'project'}}
    pages = {('eps.gdebidding.com', '/gg/cmsGGDetailjj'): (200, {}, landing),
             ('eps.gdebidding.com', root + 'jieGuo_view.html'): (200, {}, root + 'queryCGGLJieGuoByGuid.do?guid='),
             ('eps.gdebidding.com', root + 'queryCGGLJieGuoByGuid.do'): (200, {}, json.dumps(data))}
    r, _, _ = resolver(entry, pages)

    async def forbidden(*args):
        pytest.fail('hidden or mismatched data must never be rendered')

    monkeypatch.setattr(r, 'render_eps', forbidden)
    d = json.loads(await r.resolve({'detailUrl': f'https://eps.gdebidding.com/gg/cmsGGDetailjj?guid={guid}'}, 1))
    assert d['resolution']['error'] and not d['content']


async def test_native_runtime_retains_resolved_bodies_and_rejected_pdf_evidence(tmp_path, monkeypatch):
    from extrio.runtime import CrawleeRuntime
    from extrio.source_network import SourceResponse

    entry = 'https://czzx.fudan.edu.cn/cggg/list.htm'
    fields = {key: {'selector': 'jsonpath:$.' + key, 'required': True, 'transforms': ['trim']}
              for key in ['title', 'publishedAt', 'content']}
    spec = {'sourceContext': {'entrypoints': [entry], 'allowedHosts': sorted(profile_hosts(entry))},
            'sourceRevisionRef': {'sourceRevisionId': 'source_1'}, 'contract': {'fieldBindings': {
                'listTitle': 'list.listTitle', 'detailUrl': 'list.detailUrl', 'title': 'detail.title',
                'publishedAt': 'detail.publishedAt', 'content': 'detail.content'}},
            'collect': {'list': {'itemsSelector': 'css:li', 'fields': {
                'listTitle': {'selector': 'css:a::text'}, 'detailUrl': {'selector': 'css:a::attr(href)'}},
                'pagination': {'type': 'page', 'parameter': 'page', 'start': 1, 'step': 1, 'maxPages': 3}},
                'detail': {'resolution': 'official_notice_v1', 'responseType': 'json', 'fields': fields},
                'budget': {'maxPages': 3, 'maxItems': 50}}}
    collector = {'id': 'collector_docs', 'name': 'Documents', 'sourceHost': 'czzx.fudan.edu.cn',
                 'collectionVersion': 'v1', 'candidate': {'gatherSpec': spec}}
    runtime = CrawleeRuntime(tmp_path)

    async def list_page(urls, *_args):
        page = parse_qs(urlsplit(urls[0]).query).get('page', ['1'])[0]
        return {urls[0]: f'<li><a href="/{page}">Notice {page}</a></li>'}

    async def fetch(_self, url, **_kwargs):
        page = urlsplit(url).path.strip('/')
        body = '<iframe src="/body.pdf"></iframe>' if page == '2' else 'Actual notice body. ' * 20
        html = (f'<h1 class="arti_title">Notice {page}</h1><span class="arti_update">2026-10-19</span>'
                f'<div class="wp_articlecontent">{body}</div>')
        return SourceResponse(url, 200, {}, pdf_bytes(scanned=True) if page == 'body.pdf' else html.encode())

    async def progress(*_args):
        pass

    monkeypatch.setattr(runtime, '_fetch_many', list_page)
    monkeypatch.setattr(SourceNetwork, 'fetch', fetch)
    result = await runtime.run(collector, {'id': 'run_docs', 'ruleVersion': 'rule_v1'}, progress)
    assert result.metrics['listPagesFetched'] == result.metrics['detailPagesFetched'] == 3
    assert [i['decision'] for i in result.items] == ['accepted', 'rejected', 'accepted']
    rejected = result.items[1]
    assert 'requires_review' in rejected['rejectionReason'] and not rejected['content']
    assert (tmp_path / 'run_docs/attempt_1/document-002-02.pdf').read_bytes().startswith(b'%PDF-')
    assert result.evidence_digest and result.artifact_mode == 'sampled'


@pytest.mark.parametrize('unknown_request', [False, True])
async def test_eps_offline_callbacks_never_forward_post_or_auth_probe(unknown_request):
    entry = 'http://www.gdebidding.com/cgxx/index.jhtml'
    network = SourceNetwork(profile_hosts(entry))
    network.fetch = AsyncMock(side_effect=AssertionError('offline callbacks must not perform network requests'))
    resolver = OfficialDocuments(network, entry, lambda *_: None)
    frame_url = 'https://eps.gdebidding.com/gdjd-xunjia/gonggaoxinxi/jieGuo_view.html?guid=test'
    api_url = 'https://eps.gdebidding.com/gdjd-xunjia/gonggaoxinxi/queryCGGLJieGuoByGuid.do?guid=test'
    handler = None
    routed = []

    async def route(_pattern, callback):
        nonlocal handler
        handler = callback

    async def goto(*_args, **_kwargs):
        for url, method in [(frame_url, 'GET'), (api_url, 'POST'),
                            ('https://eps.gdebidding.com/gdjd-xunjia/common/nofilter/getLoginRemote.do', 'POST'),
                            *(([('https://eps.gdebidding.com/write', 'POST')]) if unknown_request else [])]:
            request = SimpleNamespace(url=url, method=method, resource_type='xhr', is_navigation_request=lambda: False)
            current = SimpleNamespace(request=request, fulfill=AsyncMock(), abort=AsyncMock())
            routed.append(current)
            await handler(current)

    body = SimpleNamespace(inner_text=AsyncMock(return_value='Public visible announcement body'),
                           locator=lambda _: SimpleNamespace(evaluate_all=AsyncMock(return_value='')))
    page = SimpleNamespace(goto=goto, wait_for_function=AsyncMock(), locator=lambda _: body,
                           content=AsyncMock(return_value='<html>Derived snapshot</html>'))
    context = SimpleNamespace(route=route, route_web_socket=AsyncMock(), new_page=AsyncMock(return_value=page), close=AsyncMock())
    resolver.browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    if unknown_request:
        with pytest.raises(ValueError, match='eps_uncached_data_request'):
            await resolver.render_eps(frame_url, '<html/>', api_url, {api_url: b'{"public":true}'})
        routed[-1].abort.assert_awaited_once()
    else:
        visible, _ = await resolver.render_eps(frame_url, '<html/>', api_url, {api_url: b'{"public":true}'})
        assert visible == 'Public visible announcement body'
        routed[1].fulfill.assert_awaited_once_with(status=200, content_type='application/json', body=b'{"public":true}')
    routed[2].abort.assert_awaited_once()
    assert resolver.render_blocked[0]['reason'] == 'anonymous_no_login'
    network.fetch.assert_not_awaited()
    context.close.assert_awaited_once()


@pytest.mark.parametrize('project_name', ['Project', ' \tProject\t '])
async def test_eps_public_unit_read_accepts_observed_numeric_receive_id(public_dns, monkeypatch, project_name):
    entry = 'http://www.gdebidding.com/cgxx/index.jhtml'
    guid = '90d51d70-d49e-4c9b-b0f0-075f1fd903a7'
    root = '/gdjd-xunjia/gonggaoxinxi/'
    template = root + 'queryCGGLJieGuoByGuid.do?guid= ' + root + 'queryBJJSByReceiveGuid.do?receiveGuid='
    data = {'jieGuoGuid': guid, 'hideForBidder': False, 'isGongKai': True, 'gongShiType': 1,
            'gongShiFaBuTimeShortText': '2026-10-19', 'xiangMu': {'xiangMuName': project_name, 'gongKaiType': 10},
            'baoJian': {'receiveGuid': '2108733227379331072', 'baoJianBianHao': 'TEST/01'}}
    pages = {('eps.gdebidding.com', '/gg/cmsGGDetailjj'): (
        200, {}, f'<iframe id="iframepage" src="{root}jieGuo_view.html?guid={guid}"></iframe>'),
        ('eps.gdebidding.com', root + 'jieGuo_view.html'): (200, {}, template),
        ('eps.gdebidding.com', root + 'queryCGGLJieGuoByGuid.do'): (200, {}, json.dumps(data)),
        ('eps.gdebidding.com', root + 'queryBJJSByReceiveGuid.do'): (200, {}, '{"baseRentUnitName":"元"}')}
    r, _, calls = resolver(entry, pages)
    r.render_blocked = []
    monkeypatch.setattr(r, 'render_eps', AsyncMock(return_value=('Project 成交结果公告\n' + 'Public body ' * 20, '<html/>')))
    d = json.loads(await r.resolve({'detailUrl': f'https://eps.gdebidding.com/gg/cmsGGDetailjj?guid={guid}',
                                   'listTitle': 'Project(包件01)成交结果公告'}, 1))
    assert not d['resolution']['error'] and d['content']
    assert any(path.endswith('queryBJJSByReceiveGuid.do') for _, _, path in calls)
    assert all(method == 'GET' for method, _, _ in calls)


@pytest.mark.parametrize('complete', [False, True])
async def test_xmu_complete_amendment_is_not_an_original_link_stub(public_dns, complete):
    title = '厦门大学图书馆设备更正及延期开标公告'
    body = ('各供应商：本项目现做如下更正。更正内容：样品接收时间及提交报价文件截止时间延期至2026年10月20日。'
            '请各供应商按修订后的时间准备文件，逾期提交无效。其余内容不变，特此公告。') if complete else (
                '本项目更正信息公告原文详见以下公告网址，供应商应当访问原公告阅读完整内容，本页仅提供原文跳转入口。')
    landing = (f'<div class="ctitle"><h1>{title}</h1><div class="info"><i>2026-10-19</i></div></div>'
               f'<div class="ccontent">{body}<p>原公告网址：<a href="/cghw/548.chtml">公告原文</a></p></div>')
    r, _, _ = resolver(XMU, {('ztb.xmu.edu.cn', '/cghw/559.chtml'): (200, {}, landing)})
    envelope = json.loads(await r.resolve({'detailUrl': 'https://ztb.xmu.edu.cn/cghw/559.chtml', 'listTitle': title}, 1))
    assert bool(envelope['content']) == complete
    assert bool(envelope['resolution']['error']) != complete
