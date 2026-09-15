import type { CollectionDetail, SourceFieldContract } from '@/api/types'

export function sourceAlignment(contract: SourceFieldContract | undefined, target: number | undefined) {
  if (!target || contract?.targetVersionNumber !== target || typeof contract.isAligned !== 'boolean') return 'unknown'
  return contract.isAligned ? 'aligned' : 'outdated'
}

export function collectionAlignment(requirement: CollectionDetail) {
  const contracts = new Map(requirement.sourceContracts?.map(contract => [contract.sourceId, contract]))
  const counts = { aligned: 0, outdated: 0, unknown: 0, total: 0 }
  for (const source of requirement.sources) {
    if (source.lifecycle === 'archived') continue
    counts.total++
    counts[sourceAlignment(contracts.get(source.id), requirement.activeVersion?.versionNumber)]++
  }
  return counts
}
