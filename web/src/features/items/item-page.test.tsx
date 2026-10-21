import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedRuns } from '@/api/fixtures'
import { ItemPage } from './item-page'

const item = seedRuns[0].items[0]

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/items/${item.id}`]}>
        <Routes><Route path="/items/:itemId" element={<ItemPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ItemPage information architecture', () => {
  it('does not claim an empty body is allowed when document resolution is rejected', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...item, content: '', decision: 'rejected',
      rejectionReason: 'pdf_image_requires_review' }), { headers: { 'Content-Type': 'application/json' } })))
    renderPage()
    await screen.findByRole('heading', { level: 1 })
    await userEvent.click(screen.getByRole('tab', { name: '质量决定' }))
    expect(screen.getByText('未取得正文，接收结果以当前质量决定为准')).toBeInTheDocument()
    expect(screen.queryByText('当前合同允许正文为空')).not.toBeInTheDocument()
  })
  it('distinguishes verified EPS package identity from identical title wording', async () => {
    const documentResolution = { kind: 'eps_public_template_render', error: null,
      renderedTitle: '项目采购成交结果公告', identityListTitles: ['项目(包件01)成交结果公告'], documents: [] }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...item, title: documentResolution.renderedTitle,
      listTitle: documentResolution.identityListTitles[0], lineage: { ...item.lineage, documentResolution } }),
      { headers: { 'Content-Type': 'application/json' } })))
    renderPage()
    await screen.findByRole('heading', { level: 1 })
    await userEvent.click(screen.getByRole('tab', { name: '质量决定' }))
    expect(screen.getByText('公告身份已核验')).toBeInTheDocument()
    expect(screen.queryByText('列表标题与详情标题一致')).not.toBeInTheDocument()
  })
  it('shows document provenance and quality errors without mounting publisher markup', async () => {
    const documentResolution = { profile: 'official_notice_v1', kind: 'embedded_pdf_text', error: 'pdf_image_requires_review',
      documents: [{ role: 'embedded_body_pdf', url: 'https://czzx.fudan.edu.cn/body.pdf', pages: 2, sha256: 'abc' }] }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...item,
      lineage: { ...item.lineage, documentResolution } }), { headers: { 'Content-Type': 'application/json' } })))
    renderPage()
    await screen.findByRole('heading', { level: 1 })
    await userEvent.click(screen.getByRole('tab', { name: '来源与谱系' }))
    expect(screen.getByRole('heading', { name: '原文解析' })).toBeInTheDocument()
    expect(screen.getByText('内嵌 PDF 文本层（非 OCR）')).toBeInTheDocument()
    expect(screen.getByText('pdf_image_requires_review')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /https:\/\/czzx.fudan.edu.cn\/body.pdf/ })).toHaveAttribute('href', 'https://czzx.fudan.edu.cn/body.pdf')
  })
  it('retains content and run lineage for a deleted source without a broken source link', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...item, collectorDeleted: true }), { headers: { 'Content-Type': 'application/json' } })))
    renderPage()
    expect(await screen.findByText('来源已删除')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: '来源与谱系' }))
    expect(screen.getByRole('link', { name: /查看运行记录/ })).toBeInTheDocument()
    expect(screen.queryAllByRole('link').some(link => link.getAttribute('href')?.startsWith('/collectors/'))).toBe(false)
  })
  it('reads HTML as inert text and offers literal source without mounting HTML', async () => {
    const content = '<article><p>采购正文</p><script>window.attacked = true</script><img src="https://example.com/tracker.png"><p hidden>不可见</p></article>'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({...item,content}), {headers:{'Content-Type':'application/json'}})))
    renderPage()
    expect(await screen.findByText('采购正文', {exact:true})).toBeInTheDocument()
    expect(document.querySelector('article img')).toBeNull()
    expect(screen.queryByText('不可见')).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', {name:'HTML'}))
    expect(document.querySelector('.item-raw-content')).toHaveTextContent(content)
    expect(document.querySelector('article img')).toBeNull()
  })
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(item), { headers: { 'Content-Type': 'application/json' } })))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('uses the shared detail navigation and leads with normalized content', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { level: 1, name: item.title })).toBeInTheDocument()
    expect(screen.queryByLabelText('Item 谱系证据')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '数据' })).not.toBeInTheDocument()

    const tablist = screen.getByRole('tablist', { name: '数据详情视图' })
    expect(tablist).toHaveAttribute('data-variant', 'line')
    expect(within(tablist).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      '数据内容',
      `版本与观察${item.observationHistory.length}`,
      '质量决定',
      '来源与谱系',
    ])
    expect(screen.getByLabelText('数据内容摘要')).toHaveTextContent('规范化数据可用')
    expect(screen.getByLabelText('数据内容摘要')).toHaveClass('detail-panel')
    expect(screen.getByRole('heading', { name: '公告内容' })).toBeInTheDocument()
  })

  it('groups revision history, quality, and lineage into task views', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('heading', { level: 1 })

    await user.click(screen.getByRole('tab', { name: `版本与观察${item.observationHistory.length}` }))
    expect(screen.getByRole('heading', { name: '版本变化' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '观察历史' })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '质量决定' }))
    expect(screen.getByRole('heading', { name: '质量决定' })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '来源与谱系' }))
    expect(screen.getByRole('heading', { name: '来源与谱系' })).toBeInTheDocument()
    const technicalDetails = screen.getByText('技术信息').closest('details')
    expect(technicalDetails).not.toHaveAttribute('open')
    expect(screen.getByRole('link', { name: /查看运行记录/ })).toHaveAttribute('href', `/runs/${item.lineage.runId}?returnTo=${encodeURIComponent(`/items/${item.id}?section=lineage`)}`)
  })

  it('surfaces a list/detail title mismatch instead of reporting a false match', async () => {
    const mismatched = { ...item, title: '详情页真实标题', listTitle: '列表页错误标题', decision: 'rejected' as const }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(mismatched), { headers: { 'Content-Type': 'application/json' } })))
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('heading', { level: 1, name: mismatched.title })

    await user.click(screen.getByRole('tab', { name: '质量决定' }))
    expect(screen.getByText('标题需要复核')).toBeInTheDocument()
    expect(screen.queryByText('列表标题与详情标题一致')).not.toBeInTheDocument()
  })
})
