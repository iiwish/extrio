import type { CandidateRule, CollectionPolicy, Collector, CollectorDetail, CollectorSchedule, HarvestItem, Run } from './types'

interface ScenarioProfile {
  key: string
  place: string
  district: string
  titles: [string, string, string]
  buyers: [string, string, string]
  budgets: [string, string, string]
}

const profiles: ScenarioProfile[] = [
  {
    key: 'beijing',
    place: '北京',
    district: '朝阳',
    titles: ['北京市朝阳区教育系统网络设备采购项目', '海淀区政务云资源扩容服务公开招标公告', '城市副中心公共空间数字化改造项目'],
    buyers: ['北京市朝阳区教育服务保障中心', '北京市海淀区政务服务管理局', '北京城市副中心管理委员会'],
    budgets: ['286 万元', '412 万元', '1,180 万元'],
  },
  {
    key: 'shanghai',
    place: '上海',
    district: '浦东',
    titles: ['上海市浦东新区智慧校园网络改造项目', '徐汇区政务云资源扩容服务采购公告', '临港新片区公共空间数字化建设项目'],
    buyers: ['上海市浦东新区教育局', '上海市徐汇区数据局', '中国（上海）自由贸易试验区临港新片区管理委员会'],
    budgets: ['318 万元', '465 万元', '1,260 万元'],
  },
  {
    key: 'guangdong',
    place: '广东',
    district: '广州',
    titles: ['广东省教育专网升级改造项目', '广州市政务云资源扩容服务采购公告', '粤港澳大湾区数据治理平台建设项目'],
    buyers: ['广东省教育技术中心', '广州市政务服务和数据管理局', '广东省政务服务数据管理局'],
    budgets: ['526 万元', '680 万元', '1,480 万元'],
  },
  {
    key: 'zhejiang',
    place: '浙江',
    district: '杭州',
    titles: ['浙江省教育数据中心基础设施升级项目', '杭州市政务云扩容服务公开招标公告', '浙江省公共数据授权运营平台建设项目'],
    buyers: ['浙江省教育技术中心', '杭州市数据资源管理局', '浙江省大数据发展管理局'],
    budgets: ['398 万元', '742 万元', '1,320 万元'],
  },
]

const fallbackProfile: ScenarioProfile = {
  key: 'source',
  place: '全国',
  district: '本地',
  titles: ['教育系统网络设备采购项目', '政务云资源扩容服务采购公告', '公共空间数字化改造项目'],
  buyers: ['教育服务保障中心', '政务服务管理局', '公共资源管理中心'],
  budgets: ['286 万元', '412 万元', '1,180 万元'],
}

type CollectorContext = Pick<Collector, 'id' | 'name' | 'sourceUrl' | 'sourceHost' | 'collectionId' | 'collectionVersion'>

function scenarioFor(collector: Pick<Collector, 'name' | 'sourceUrl' | 'sourceHost'>) {
  const source = `${collector.name} ${collector.sourceUrl} ${collector.sourceHost}`.toLowerCase()
  if (source.includes('gdzwfw') || source.includes('gdcatalog')) return profiles.find((profile) => profile.key === 'guangdong')!
  if (source.includes('zcygov') || source.includes('zjzwfw')) return profiles.find((profile) => profile.key === 'zhejiang')!
  return profiles.find((profile) => source.includes(profile.key) || source.includes(profile.place)) ?? fallbackProfile
}

function itemLineage(collector: CollectorContext, runId: string, ruleVersion: string, suffix: string, accepted = true) {
  const profile = scenarioFor(collector)
  return {
    sourceRevision: `src_rev_${profile.key}_07`,
    collectionVersion: collector.collectionVersion,
    ruleVersion,
    runId,
    observationId: accepted ? `obs_${runId.replace('run_', '')}_${suffix.toLowerCase()}` : null,
    artifactId: `artifact_${profile.key}_${suffix.toLowerCase()}`,
  }
}

function digest(seed: string) {
  const hex = [...seed].reduce((value, character) => value + character.charCodeAt(0), 0).toString(16).slice(-1)
  return `sha256:${hex.repeat(64)}`
}

export function collectionPolicyFor(collectorId: string, version = 1): CollectionPolicy {
  const id = `policy_${collectorId.replace('collector_', '')}_v${version}`
  return {
    id,
    collectorId,
    version,
    mode: 'rolling_incremental',
    initialWindowDays: 30,
    lookbackDays: 3,
    consecutiveOlderPages: 2,
    maxPages: 20,
    maxItems: 300,
    timezone: 'Asia/Shanghai',
    createdAt: '2026-08-30T08:00:00Z',
    digest: digest(id),
  }
}

export function scheduleFor(collectorId: string, revision = 1, enabled = false): CollectorSchedule {
  return {
    id: `schedule_${collectorId.replace('collector_', '')}`,
    collectorId,
    revision,
    enabled,
    cronExpression: '0 8 * * *',
    timezone: 'Asia/Shanghai',
    overlapPolicy: 'forbid',
    lastTriggeredAt: enabled ? '2026-09-01T00:00:00Z' : null,
    nextRunAt: enabled ? '2026-09-02T00:00:00Z' : null,
    updatedAt: '2026-09-01T00:00:00Z',
  }
}

function createGatherSpec(
  collector: Pick<Collector, 'id' | 'sourceUrl' | 'sourceHost' | 'collectionId'>,
  profile: ScenarioProfile,
  mode: CandidateRule['mode'],
  pagination: CandidateRule['pagination'],
): CandidateRule['gatherSpec'] {
  type GatherFields = CandidateRule['gatherSpec']['collect']['list']['fields']
  const titleRule = {
    selector: 'css:h1.notice-title::text',
    valueType: 'string' as const,
    required: true,
    onError: 'reject_item' as const,
    multipleMatchPolicy: 'error' as const,
    transforms: ['trim' as const, 'collapse_whitespace' as const],
  }
  const buyerRule = {
    selector: 'css:.meta [data-field="buyer"]::text',
    valueType: 'string' as const,
    required: true,
    onError: 'reject_item' as const,
    multipleMatchPolicy: 'error' as const,
    transforms: ['trim' as const],
  }
  const publishedAtRule = {
    selector: 'css:time[datetime]::attr(datetime)',
    valueType: 'datetime' as const,
    required: true,
    onError: 'reject_item' as const,
    multipleMatchPolicy: 'error' as const,
    transforms: ['trim' as const],
    datetimeFormat: 'RFC3339' as const,
    defaultTimezone: 'Asia/Shanghai',
  }
  const budgetRule = {
    selector: 'css:.notice-budget .amount::text',
    valueType: 'string' as const,
    required: false,
    onError: 'null' as const,
    multipleMatchPolicy: 'first' as const,
    transforms: ['trim' as const],
  }
  const listFields: GatherFields = mode === 'single'
    ? { title: titleRule, buyer: buyerRule, publishedAt: publishedAtRule, budget: budgetRule }
    : {
        listTitle: {
          ...titleRule,
          selector: 'css:a.notice-title::text',
        },
        listPublishedAt: publishedAtRule,
        detailUrl: {
          selector: 'css:a.notice-title::attr(href)',
          valueType: 'url' as const,
          required: true,
          onError: 'reject_item' as const,
          multipleMatchPolicy: 'error' as const,
          transforms: ['trim' as const, 'absolute_url' as const],
        },
      }
  const schemaProperties = {
    detailUrl: { type: ['string', 'null'], format: 'uri' },
    title: { type: 'string', minLength: 1 },
    buyer: { type: 'string', minLength: 1 },
    publishedAt: { type: 'string', format: 'date-time' },
    budget: { type: ['string', 'null'] },
  }
  const collect = {
    list: {
      request: { entrypointIndex: 0, method: 'GET' as const, headers: { Accept: 'text/html,application/xhtml+xml' }, query: {} },
      responseType: 'html' as const,
      itemsSelector: mode === 'single' ? 'css:body' : 'css:.notice-list > li',
      fields: listFields,
      pagination: pagination.type === 'page'
        ? { ...pagination, location: 'query' as const }
        : pagination,
    },
    ...(mode === 'list_detail' ? {
      detail: {
        request: { urlTemplate: '{{detailUrl}}', method: 'GET' as const, headers: { Accept: 'text/html,application/xhtml+xml' } },
        responseType: 'html' as const,
        fields: { title: titleRule, buyer: buyerRule, publishedAt: publishedAtRule, budget: budgetRule },
      },
    } : {}),
    requestRetry: { maxAttempts: 3, initialDelayMs: 500, maxDelayMs: 5000 },
    budget: { maxPages: Math.max(1, pagination.type === 'none' ? 1 : pagination.maxPages), maxItems: 10000, maxDurationSeconds: 3600, maxTotalBytes: 1073741824, onExceeded: 'partial' as const },
  }

  return {
    schemaVersion: 'extrio.gather.v1',
    ruleVersionId: `rule_${profile.key}_candidate`,
    tenantId: 'tenant_demo',
    collectorId: collector.id,
    collectionVersionRef: { collectionId: collector.collectionId, collectionVersionId: 'collection_version_tender_004', version: '4.0' },
    sourceRevisionRef: { sourceId: `source_${profile.key}`, sourceRevisionId: `source_revision_${profile.key}_007`, configDigest: digest(`${profile.key}:source`) },
    compiler: {
      name: 'extrio-compiler',
      version: '0.2.0',
      compiledAt: '2026-08-30T08:00:00Z',
      inputDigest: digest(`${profile.key}:input`),
      overrideRefs: [],
      agent: { provider: 'prototype', model: 'candidate-compiler', promptVersion: '1.0', toolchainVersion: '1.0' },
    },
    runtimeCompatibility: {
      runtimeName: 'extrio-python',
      minVersion: '0.2.0',
      maxVersionExclusive: '0.3.0',
      dialectVersion: '1.0',
      parserVersion: '1.0',
      tzdbVersion: '2026a',
      unicodeVersion: '17.0',
    },
    contract: {
      identityFields: [mode === 'single' ? 'title' : 'detailUrl'],
      fingerprintFields: ['title', 'buyer', 'publishedAt', 'budget'],
      outputContractDigest: digest('tender:output'),
      normalizedItemSchema: {
        $schema: 'https://json-schema.org/draft/2020-12/schema',
        type: 'object',
        properties: schemaProperties,
        required: ['title', 'buyer', 'publishedAt'],
        additionalProperties: false,
      },
      quality: { requiredFieldCompleteness: 0.95, maxItemErrorRatio: 0.05, emptyResultPolicy: 'suspect' },
    },
    sourceContext: {
      entrypoints: [collector.sourceUrl],
      allowedHosts: [collector.sourceHost],
      transport: 'http',
      rateLimit: { rps: 2, burst: 4, maxConcurrency: 2 },
      requestPolicy: { userAgent: 'Extrio/Collector 0.2', timeoutMs: 30000, maxResponseBytes: 20971520, maxRedirects: 3 },
    },
    collect,
    output: {
      rawRetentionDays: 30,
      emitUnchanged: false,
      sinks: [{
        sinkId: 'sink_tender_webhook',
        sinkVersionId: 'sink_version_webhook_001',
        type: 'webhook',
        eventMode: 'upsert',
        deliveryPolicy: { maxAttempts: 8, initialDelaySeconds: 5, maxDelaySeconds: 21600, timeoutSeconds: 30, totalWindowSeconds: 172800 },
      }],
    },
    integrity: { digestAlgorithm: 'sha256', ruleDigest: digest(`${profile.key}:rule`) },
  }
}

export function createCandidateRule(collector: Pick<Collector, 'id' | 'name' | 'sourceUrl' | 'sourceHost' | 'collectionId'>): CandidateRule {
  const profile = scenarioFor(collector)
  const origin = new URL(collector.sourceUrl).origin
  const mode: CandidateRule['mode'] = /(?:single|detail-only)/.test(new URL(collector.sourceUrl).pathname) ? 'single' : 'list_detail'
  const useNextLink = profile.key === 'shanghai'
  const pagination: CandidateRule['pagination'] = mode === 'single'
    ? { type: 'none' }
    : useNextLink
    ? { type: 'next_link', selector: 'css:a.pagination-next', maxPages: 20, allowCrossHost: false }
    : { type: 'page', parameter: 'page', start: 1, step: 1, maxPages: 20, stopWhenNoItems: true }
  return {
    id: `candidate_rule_${profile.key}_019`,
    digest: digest(`${profile.key}:candidate-rule`),
    mode,
    listSelector: mode === 'single' ? 'css:body' : 'css:.notice-list > li',
    detailLinkSelector: mode === 'single' ? null : 'css:a.notice-title',
    pagination,
    discovery: {
      listPagesSampled: 3,
      detailUrlsDiscovered: mode === 'single' ? 0 : 12,
      detailPagesValidated: mode === 'single' ? 0 : 3,
      detailUrlSamples: mode === 'single' ? [] : ['4f82', 'a19c', '93d1'].map((suffix) => `${origin}/notice/20260830/${suffix}`),
    },
    passedChecks: 18,
    warningChecks: 1,
    fields: [
      {
        key: 'title',
        label: '项目名称',
        selector: 'css:h1.notice-title',
        required: true,
        confidence: 0.99,
        sample: profile.titles[0],
        evidence: `<h1 class="notice-title">${profile.titles[0]}</h1>`,
        warning: null,
      },
      {
        key: 'buyer',
        label: '采购单位',
        selector: 'css:.meta [data-field="buyer"]',
        required: true,
        confidence: 0.96,
        sample: profile.buyers[0],
        evidence: `<span data-field="buyer">${profile.buyers[0]}</span>`,
        warning: null,
      },
      {
        key: 'publishedAt',
        label: '发布日期',
        selector: 'css:time[datetime]',
        required: true,
        confidence: 0.98,
        sample: '2026-08-30 09:20',
        evidence: '<time datetime="2026-08-30T09:20:00+08:00">2026-08-30</time>',
        warning: null,
      },
      {
        key: 'budget',
        label: '预算金额',
        selector: 'css:.notice-budget .amount',
        required: false,
        confidence: 0.84,
        sample: profile.budgets[0],
        evidence: `<span class="amount">${profile.budgets[0]}</span>`,
        warning: '25% 的详情页未披露预算；需要接受风险或排除此字段。',
      },
    ],
    gatherSpec: createGatherSpec(collector, profile, mode, pagination),
  }
}

export function createItemsForCollector(collector: CollectorContext, runId: string, ruleVersion: string): HarvestItem[] {
  const profile = scenarioFor(collector)
  const origin = new URL(collector.sourceUrl).origin
  const suffixes = ['4F82', 'A19C', '93D1'] as const
  const observedAt = '2026-08-30 09:43'
  const accepted = suffixes.map((suffix, index): HarvestItem => ({
    id: `item_${profile.key}_${suffix}`,
    collectorId: collector.id,
    collectorName: collector.name,
    sourceHost: collector.sourceHost,
    listTitle: profile.titles[index],
    title: profile.titles[index],
    buyer: profile.buyers[index],
    region: `${profile.place} · ${index === 0 ? profile.district : index === 1 ? '中心城区' : '全域'}`,
    publishedAt: index === 0 ? '2026-08-30 09:20' : index === 1 ? '2026-08-30 08:45' : '2026-08-29 17:18',
    budget: profile.budgets[index],
    content: `${profile.titles[index]}的采购公告正文，包含采购范围、资格要求和执行说明。`,
    sourceUrl: `${origin}/notice/20260830/${suffix.toLowerCase()}`,
    decision: 'accepted',
    changeType: index === 1 ? 'updated' : 'new',
    rejectionReason: null,
    entityKey: `${profile.key}:20260830:${suffix.toLowerCase()}`,
    revision: index === 1 ? 2 : 1,
    observedAt,
    changeSummary: index === 1 ? [{ field: 'budget', before: '金额未披露', after: profile.budgets[index] }] : [],
    observationHistory: [
      ...(index === 1 ? [{ id: `obs_previous_${profile.key}`, runId: `run_previous_${profile.key}`, observedAt: '2026-08-29 09:12', outcome: 'accepted' as const }] : []),
      { id: `obs_${runId}_${suffix.toLowerCase()}`, runId, observedAt, outcome: 'accepted' },
    ],
    lineage: itemLineage(collector, runId, ruleVersion, suffix),
  }))

  return [
    ...accepted,
    {
      id: `item_${profile.key}_BROKEN`,
      collectorId: collector.id,
      collectorName: collector.name,
      sourceHost: collector.sourceHost,
      listTitle: `${profile.place} 2026 年信息化服务采购公告`,
      title: `${profile.place} 2026 年信息化服务采购公告`,
      buyer: '字段缺失',
      region: profile.place,
      publishedAt: '2026-08-29 16:02',
      budget: '未披露',
      content: '公告正文已抓取，但必填质量字段未通过校验。',
      sourceUrl: `${origin}/notice/20260829/broken`,
      decision: 'rejected',
      changeType: null,
      rejectionReason: '必填字段 buyer 未通过非空质量门',
      entityKey: `${profile.key}:20260829:broken`,
      revision: null,
      observedAt,
      changeSummary: [],
      observationHistory: [],
      lineage: itemLineage(collector, runId, ruleVersion, 'BROKEN', false),
    },
  ]
}

const beijingCollector: Collector = {
  id: 'collector_beijing_tender',
  name: '北京市公共资源交易标讯',
  intent: '采集北京市公开招标公告，提取项目、采购单位、发布时间、预算与详情链接。',
  sourceUrl: 'https://ggzyfw.beijing.gov.cn/jyxxcggg/',
  sourceHost: 'ggzyfw.beijing.gov.cn',
  status: 'ready_review',
  collectionId: 'collection_nationwide_tender',
  collectionName: '全国公共资源交易标讯',
  collectionVersion: 'tender_notice_v4',
  activeRuleVersion: null,
  activeCollectionPolicyId: 'policy_beijing_tender_v1',
  activeOperationId: null,
  latestRunId: null,
  updatedAt: '刚刚',
}

const shanghaiCollector: Collector = {
  id: 'collector_shanghai_procurement',
  name: '上海政府采购公告',
  intent: '采集公开招标和竞争性磋商公告。',
  sourceUrl: 'https://www.zfcg.sh.gov.cn/',
  sourceHost: 'www.zfcg.sh.gov.cn',
  status: 'published',
  collectionId: 'collection_nationwide_tender',
  collectionName: '全国公共资源交易标讯',
  collectionVersion: 'tender_notice_v4',
  activeRuleVersion: 'rule_v3',
  activeCollectionPolicyId: 'policy_shanghai_procurement_v1',
  activeOperationId: null,
  latestRunId: 'run_0842',
  updatedAt: '12 分钟前',
}

export const candidateRule = createCandidateRule(beijingCollector)
export const demoItems = createItemsForCollector(beijingCollector, 'run_preview_beijing', 'candidate')
const shanghaiCandidate = createCandidateRule(shanghaiCollector)
const shanghaiItems = createItemsForCollector(shanghaiCollector, 'run_0842', 'rule_v3')

export const seedCollectors: CollectorDetail[] = [
  {
    ...beijingCollector,
    candidate: candidateRule,
    previewItems: demoItems,
    reviewDecisions: null,
    collectionPolicy: collectionPolicyFor(beijingCollector.id),
    checkpoint: null,
    schedule: scheduleFor(beijingCollector.id),
  },
  {
    ...shanghaiCollector,
    candidate: shanghaiCandidate,
    previewItems: shanghaiItems,
    reviewDecisions: { title: 'approved', buyer: 'approved', publishedAt: 'approved', budget: 'risk_accepted' },
    collectionPolicy: collectionPolicyFor(shanghaiCollector.id),
    checkpoint: {
      collectorId: shanghaiCollector.id,
      policyVersionId: 'policy_shanghai_procurement_v1',
      lastSuccessfulRunId: 'run_0730',
      watermark: '2026-08-30',
      advancedAt: '2026-08-30T01:43:00Z',
    },
    schedule: scheduleFor(shanghaiCollector.id, 1, true),
  },
]

export const seedRuns: Run[] = [
  {
    id: 'run_0842',
    operationId: null,
    collectorId: shanghaiCollector.id,
    collectorName: shanghaiCollector.name,
    collectionMode: 'list_detail',
    status: 'partially_succeeded',
    startedAt: '2026-08-30 09:42',
    startedAtIso: '2026-08-30T01:42:00Z',
    duration: '1m 38s',
    acceptedCount: 3,
    rejectedCount: 1,
    pagesFetched: 9,
    listPagesFetched: 5,
    detailUrlsDiscovered: 4,
    detailPagesFetched: 4,
    recordsOutsideWindow: 18,
    duplicateDetailUrls: 1,
    newItems: 2,
    updatedItems: 1,
    unchangedItems: 0,
    paginationStopReason: 'next_link_exhausted',
    ruleVersion: 'rule_v3',
    ruleDigest: digest('shanghai:rule-v3'),
    ruleAttestationId: 'attestation_shanghai_rule_v3',
    signingKeyId: 'signingkey_local_dev_v1',
    trustRevision: 1,
    integrityStatus: 'verified',
    policyContextStatus: 'fixed',
    policyVersion: 'policy_shanghai_procurement_v1',
    policyDigest: collectionPolicyFor(shanghaiCollector.id).digest,
    executionMode: 'initial',
    windowStart: '2026-08-01',
    checkpointBefore: null,
    checkpointAfter: null,
    artifactMode: 'sampled',
    summary: '1 个 Item 因必填字段 buyer 为空被拒绝；3 个 accepted Item 已冻结。',
    recoveryAction: '检查拒绝项的 Source 结构；如结构已漂移，返回 Collector 重新探索并发布新规则。',
    items: shanghaiItems,
  },
]
