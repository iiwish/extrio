import { describe, expect, it } from 'vitest'
import type { HarvestItem } from '@/api/types'
import { demoItems } from '@/api/fixtures'
import { collectorSourceLabel } from '@/features/collectors/collector-presentation'
import { latestEntities } from './items-page'

describe('ItemsPage entity projection', () => {
  it('keeps the newest observation for each Collector entity', () => {
    const original = demoItems[0]
    const older = { ...original, id: 'item_older', observedAt: '2026-08-29 09:00' }
    const newer = { ...original, id: 'item_newer', observedAt: '2026-08-31 12:00' }
    const result = latestEntities([older, newer])

    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('item_newer')
  })

  it('does not merge the same entity key across Collectors', () => {
    const original = demoItems[0]
    const anotherCollector = { ...original, id: 'item_other', collectorId: 'collector_other' } satisfies HarvestItem
    const result = latestEntities([original, anotherCollector])

    expect(result).toHaveLength(2)
  })

  it('does not repeat the host when the Collector name is the same', () => {
    expect(collectorSourceLabel('ggzyfw.beijing.gov.cn', 'ggzyfw.beijing.gov.cn')).toBe('ggzyfw.beijing.gov.cn')
    expect(collectorSourceLabel('北京公共资源交易', 'ggzyfw.beijing.gov.cn')).toBe('北京公共资源交易 · ggzyfw.beijing.gov.cn')
  })
})
