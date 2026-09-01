import type { components } from './generated/schema'

type Schemas = components['schemas']

export type CollectorStatus = Schemas['CollectorStatus']
export type RunStatus = Schemas['RunStatus']
export type OperationStatus = Schemas['OperationStatus']
export type OperationPhase = Schemas['OperationPhase']
export type CollectionMode = Schemas['CollectionMode']
export type ItemDecision = Schemas['ItemDecision']
export type FieldReviewDecision = Schemas['FieldReviewDecision']
export type ModelProvider = Schemas['ModelProvider']

export type PlatformError = Schemas['PlatformError']
export type Operation = Schemas['Operation']
export type CandidateField = Schemas['CandidateField']
export type GatherSpec = Omit<Schemas['gather-spec.schema'], '$defs'>
export type CandidateRule = Omit<Schemas['CandidateRule'], 'gatherSpec'> & { gatherSpec: GatherSpec }
export type ItemLineage = Schemas['ItemLineage']
export type HarvestItem = Schemas['HarvestResult']
export type Run = Schemas['Run']
export type Collector = Schemas['Collector']
export type CollectionPolicy = Schemas['CollectionPolicy']
export type CollectionPolicyInput = Schemas['CollectionPolicyInput']
export type CollectorSchedule = Schemas['CollectorSchedule']
export type CollectorScheduleInput = Schemas['CollectorScheduleInput']
export type CollectorCheckpoint = Schemas['CollectorCheckpoint']
export type CollectorDetail = Omit<Schemas['CollectorDetail'], 'candidate'> & { candidate: CandidateRule | null }
export type CreateCollectorInput = Schemas['CreateCollectorInput']
export type UpdateCollectorInput = Schemas['UpdateCollectorInput']
export type CandidateRuleEditInput = Schemas['CandidateRuleEditInput']
export type CreateCollectorsInput = Schemas['CreateCollectorsInput']
export type BatchCollectorImportItem = Omit<Schemas['BatchCollectorImportItem'], 'collector'> & { collector: CollectorDetail | null }
export type BatchCollectorImportResult = Omit<Schemas['BatchCollectorImportResult'], 'results'> & { results: BatchCollectorImportItem[] }
export type CollectorPage = Omit<Schemas['CollectorPage'], 'items'> & { items: CollectorDetail[] }
export type RunPage = Schemas['RunPage']
export type ItemPage = Schemas['ItemPage']
export type ModelSetting = Schemas['ModelSetting']
export type ModelSettingInput = Schemas['ModelSettingInput']
export type ModelConfiguration = Schemas['ModelConfiguration']
export type ModelConfigurationInput = Schemas['ModelConfigurationInput']
export type ModelProviderConfiguration = Schemas['ModelProviderConfiguration']
export type ModelProviderConfigurationInput = Schemas['ModelProviderConfigurationInput']
export type ModelConfigurationItem = Schemas['ModelConfigurationItem']
export type ModelConfigurationItemInput = Schemas['ModelConfigurationItemInput']
