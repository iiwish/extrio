import { describe, expect, it } from 'vitest'
import { collectorCreationContext, inspectSourceDrafts, inspectSourceUrls } from './new-collector-page'
import { SourceFileError, parseSourceFile } from './source-file-import'

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
      returnPath: '/collections/collection_procurement',
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
  it('rejects bare site roots and unsupported import modes', () => {
    const drafts = parseSourceFile('sources.csv', [
      'entryUrl,mode',
      'https://a.example.gov.cn/,',
      'https://a.example.gov.cn/notices,discover',
    ].join('\n'))
    expect(inspectSourceDrafts(drafts).map((row) => row.status)).toEqual(['invalid', 'invalid'])
    expect(inspectSourceDrafts(drafts).map((row) => row.message)).toEqual([
      '请填写具体列表页，不要使用站点根目录',
      '当前仅支持 exact 模式',
    ])
  })
})

describe('parseSourceFile', () => {
  it('parses a real CSV by header and preserves quoted commas and semicolons', () => {
    const rows = parseSourceFile('collectors.csv', [
      '\uFEFFentryUrl,mode,name,scopeHint,notes',
      '"https://a.example.gov.cn/notices",,"市级,采购意向","货物；服务","not a URL, still metadata"',
      '"https://b.example.gov.cn/list",exact,区级采购意向,工程,second',
    ].join('\r\n'))

    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({
      entryUrl: 'https://a.example.gov.cn/notices',
      mode: 'exact',
      name: '市级,采购意向',
      scopeHint: '货物；服务',
      lineNumber: 2,
    })
  })

  it('accepts legacy URL, name and scope header aliases', () => {
    const rows = parseSourceFile('collectors.csv', 'sourceUrl,siteName,contentScope\nhttps://a.example.gov.cn/notices,A站,公开招标')
    expect(rows[0]).toMatchObject({ entryUrl: 'https://a.example.gov.cn/notices', name: 'A站', scopeHint: '公开招标' })
  })

  it('accepts the minimal one-column CSV contract', () => {
    const rows = parseSourceFile('collectors.csv', 'entryUrl\nhttps://a.example.gov.cn/notices')
    expect(rows[0]).toMatchObject({ entryUrl: 'https://a.example.gov.cn/notices', mode: 'exact' })
  })

  it('treats TXT as one URL per line instead of splitting punctuation', () => {
    const rows = parseSourceFile('collectors.txt', 'https://a.example.gov.cn/list?q=a,b;c\nhttps://b.example.gov.cn/notices')
    expect(rows.map((row) => row.entryUrl)).toEqual([
      'https://a.example.gov.cn/list?q=a,b;c',
      'https://b.example.gov.cn/notices',
    ])
  })

  it('reports a missing URL column with a stable error code', () => {
    expect(() => parseSourceFile('collectors.csv', 'name,notes\nA,missing URL')).toThrowError(SourceFileError)
    try {
      parseSourceFile('collectors.csv', 'name,notes\nA,missing URL')
    } catch (error) {
      expect(error).toMatchObject({ code: 'missingUrlColumn' })
    }
  })

  it('rejects unquoted cells that create extra CSV columns', () => {
    const malformedCsv = [
      'entryUrl,name',
      'https://a.example.gov.cn/notices,Procurement,unexpected',
    ].join('\n')
    expect(() => parseSourceFile('collectors.csv', malformedCsv)).toThrowError(SourceFileError)
    try {
      parseSourceFile('collectors.csv', malformedCsv)
    } catch (error) {
      expect(error).toMatchObject({ code: 'parseFailed' })
    }
  })

  it.each([
    ['collectors.json', '[]', 'unsupportedFormat'],
    ['collectors.csv', 'entryUrl\n', 'empty'],
    ['collectors.csv', 'entryUrl\nhttps://a.example.gov.cn/\uFFFD', 'encoding'],
  ])('reports %s import failures with stable error codes', (fileName, contents, code) => {
    try {
      parseSourceFile(fileName, contents)
      expect.fail('expected the import to fail')
    } catch (error) {
      expect(error).toMatchObject({ code })
    }
  })

  it('rejects files over the 1000-row contract', () => {
    const rows = Array.from({ length: 1001 }, (_, index) => `https://a.example.gov.cn/notices/${index}`)
    try {
      parseSourceFile('collectors.txt', rows.join('\n'))
      expect.fail('expected the import to fail')
    } catch (error) {
      expect(error).toMatchObject({ code: 'tooManyRows' })
    }
  })
})
