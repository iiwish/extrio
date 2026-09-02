import { describe, expect, it } from 'vitest'
import { collectorCreationContext, inspectSourceUrls, mergeSourceLines, parseImportedSourceUrls } from './new-collector-page'

describe('collectorCreationContext', () => {
  it('starts a new requirement when the list is not filtered', () => {
    expect(collectorCreationContext(new URLSearchParams())).toEqual({
      collectionId: '',
      mode: 'new',
      returnPath: '/collectors',
    })
  })

  it('reuses the requirement carried from the filtered list', () => {
    expect(collectorCreationContext(new URLSearchParams('collection=collection_procurement'))).toEqual({
      collectionId: 'collection_procurement',
      mode: 'existing',
      returnPath: '/collectors?collection=collection_procurement',
    })
  })
})

describe('inspectSourceUrls', () => {
  it('accepts anonymous HTTP and HTTPS sources while reporting duplicates and invalid schemes', () => {
    const rows = inspectSourceUrls([
      'https://a.example.gov.cn/notices',
      'https://b.example.gov.cn/list',
      'https://a.example.gov.cn/notices',
      'http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_1.htm',
      'ftp://files.example.gov.cn/list',
      'not-a-url',
    ].join('\n'))

    expect(rows.map((row) => row.status)).toEqual(['valid', 'valid', 'duplicate', 'valid', 'invalid', 'invalid'])
    expect(rows[0].normalized).toBe('https://a.example.gov.cn/notices')
    expect(rows[3].message).toBe('可导入 · 匿名 HTTP 风险已标记')
    expect(rows[4].message).toBe('仅支持 HTTP 或 HTTPS')
  })

  it('allows loopback HTTP only as a local development source', () => {
    const rows = inspectSourceUrls('http://127.0.0.1:8000/demo/tenders')
    expect(rows).toHaveLength(1)
    expect(rows[0].status).toBe('valid')
  })
})

describe('parseImportedSourceUrls', () => {
  it('splits file content on newlines, commas and semicolons while trimming and dropping empties', () => {
    const fileText = [
      'https://a.example.gov.cn/notices',
      '',
      'https://b.example.gov.cn/list, https://c.example.gov.cn/detail;',
      '  https://d.example.gov.cn/rank  ',
      ',;',
    ].join('\n')

    expect(parseImportedSourceUrls(fileText)).toEqual([
      'https://a.example.gov.cn/notices',
      'https://b.example.gov.cn/list',
      'https://c.example.gov.cn/detail',
      'https://d.example.gov.cn/rank',
    ])
  })

  it('dedupes within the file and preserves first-seen order', () => {
    const fileText = 'https://a.example.gov.cn,https://b.example.gov.cn\nhttps://a.example.gov.cn\nHTTPS://A.EXAMPLE.GOV.CN'
    expect(parseImportedSourceUrls(fileText)).toEqual([
      'https://a.example.gov.cn',
      'https://b.example.gov.cn',
      'HTTPS://A.EXAMPLE.GOV.CN',
    ])
  })
})

describe('mergeSourceLines', () => {
  it('keeps existing lines, skips duplicates and reports added and skipped counts', () => {
    const merged = mergeSourceLines(
      'https://a.example.gov.cn\nhttps://b.example.gov.cn',
      ['https://b.example.gov.cn', 'https://c.example.gov.cn', 'https://d.example.gov.cn'],
    )

    expect(merged).toEqual({
      text: 'https://a.example.gov.cn\nhttps://b.example.gov.cn\nhttps://c.example.gov.cn\nhttps://d.example.gov.cn',
      added: 2,
      skipped: 1,
    })
  })

  it('trims existing lines, drops blanks and compares after trim', () => {
    const merged = mergeSourceLines('  https://a.example.gov.cn  \n\n', ['https://a.example.gov.cn'])

    expect(merged).toEqual({ text: 'https://a.example.gov.cn', added: 0, skipped: 1 })
  })
})
