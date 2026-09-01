import { describe, expect, it } from 'vitest'
import { collectorCreationContext, inspectSourceUrls } from './new-collector-page'

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
