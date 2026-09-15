import { seedCollectors } from '@/api/fixtures'
import type { CollectionDetail } from '@/api/types'

export function requirement(overrides: Partial<CollectionDetail> = {}): CollectionDetail {
  return {
    id: 'collection_nationwide_tender', name: '全国公共资源交易标讯', intent: 'Collect notices',
    collectionVersion: 'tender_notice_v4', status: 'active', revision: 1,
    createdAt: '2026-09-06T00:00:00Z', updatedAt: '2026-09-06T00:00:00Z',
    sourceCount: seedCollectors.length, publishedSourceCount: 1, sources: seedCollectors,
    ...overrides,
  }
}
