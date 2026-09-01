import { describe, expect, it } from 'vitest'
import {
  candidateRule,
  createCandidateRule,
  createItemsForCollector,
  demoItems,
  seedCollectors,
  seedRuns,
} from './fixtures'

describe('prototype contract fixtures', () => {
  it('contains the reviewable tender field contract', () => {
    expect(candidateRule.fields.map((field) => field.key)).toEqual([
      'title',
      'buyer',
      'publishedAt',
      'budget',
    ])
    expect(candidateRule.fields.filter((field) => field.required)).toHaveLength(3)
  })

  it('contains accepted, rejected and traceable Items', () => {
    const accepted = demoItems.filter((item) => item.decision === 'accepted')
    const rejected = demoItems.filter((item) => item.decision === 'rejected')
    expect(accepted).toHaveLength(3)
    expect(rejected).toHaveLength(1)
    expect(accepted.every((item) => Object.values(item.lineage).every(Boolean))).toBe(true)
    expect(rejected[0].revision).toBeNull()
    expect(rejected[0].lineage.observationId).toBeNull()
    expect(rejected[0].observationHistory).toEqual([])
  })

  it('keeps every Run, RuleVersion and Item lineage on the same frozen version', () => {
    for (const run of seedRuns) {
      expect(run.items.every((item) => item.lineage.runId === run.id)).toBe(true)
      expect(run.items.every((item) => item.lineage.ruleVersion === run.ruleVersion)).toBe(true)
      expect(run.items.every((item) => item.collectorId === run.collectorId)).toBe(true)
    }
    const published = seedCollectors.filter((collector) => collector.status === 'published')
    expect(published.every((collector) => collector.reviewDecisions && !Object.values(collector.reviewDecisions).includes('pending'))).toBe(true)
    expect(seedCollectors.every((collector) => collector.collectionPolicy?.mode === 'rolling_incremental')).toBe(true)
    expect(seedRuns.every((run) => run.policyVersion && run.policyDigest && run.windowStart)).toBe(true)
  })

  it('builds candidate evidence and Item URLs from the Collector Source scenario', () => {
    const collector = seedCollectors.find((row) => row.id === 'collector_shanghai_procurement')!
    const candidate = createCandidateRule(collector)
    const items = createItemsForCollector(collector, 'run_test', 'rule_v9')

    expect(candidate.fields[0].sample).toContain('上海')
    expect(candidate.gatherSpec.schemaVersion).toBe('extrio.gather.v1')
    expect(candidate.gatherSpec.collectorId).toBe(collector.id)
    expect(candidate.pagination.type).toBe('next_link')
    expect(candidate.discovery.detailUrlsDiscovered).toBeGreaterThan(candidate.discovery.detailPagesValidated)
    expect(candidate.discovery.detailUrlSamples.every((url) => new URL(url).host === collector.sourceHost)).toBe(true)
    expect(items.every((item) => item.sourceHost === collector.sourceHost)).toBe(true)
    expect(items.every((item) => new URL(item.sourceUrl).host === collector.sourceHost)).toBe(true)
    expect(items.every((item) => item.lineage.ruleVersion === 'rule_v9')).toBe(true)

    const guangdong = {
      id: 'collector_guangdong_tender',
      name: '广东标讯采集',
      sourceUrl: 'https://ygp.gdzwfw.gov.cn/',
      sourceHost: 'ygp.gdzwfw.gov.cn',
      collectionId: 'collection_tender',
      collectionVersion: 'tender_notice_v4',
    }
    expect(createCandidateRule(guangdong).fields[0].sample).toContain('广东')
    expect(createCandidateRule(guangdong).pagination.type).toBe('page')
    expect(createItemsForCollector(guangdong, 'run_gd', 'rule_v2').every((item) => item.title.includes('广东') || item.title.includes('广州') || item.title.includes('粤港澳'))).toBe(true)

    const single = createCandidateRule({ ...guangdong, sourceUrl: 'https://ygp.gdzwfw.gov.cn/single' })
    expect(single.mode).toBe('single')
    expect(single.detailLinkSelector).toBeNull()
    expect(single.pagination.type).toBe('none')
    expect(single.gatherSpec.collect.detail).toBeUndefined()
  })
})
