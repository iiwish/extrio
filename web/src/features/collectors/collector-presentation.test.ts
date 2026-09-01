import { describe, expect, it } from 'vitest'
import { collectorDisplayName, sourceLocationLabel } from './collector-presentation'

describe('collector presentation', () => {
  it('removes opaque batch ordering from generated collector names', () => {
    expect(collectorDisplayName('www.zycg.gov.cn · 入口 2')).toBe('www.zycg.gov.cn')
    expect(collectorDisplayName('北京市公共资源交易标讯')).toBe('北京市公共资源交易标讯')
  })

  it('uses the source path to distinguish collectors on the same host', () => {
    expect(sourceLocationLabel(
      'https://www.zycg.gov.cn/freecms/site/zygjjgzfcgzx/cggg/index.html',
      'www.zycg.gov.cn',
    )).toBe('www.zycg.gov.cn / zygjjgzfcgzx/cggg')
  })
})
