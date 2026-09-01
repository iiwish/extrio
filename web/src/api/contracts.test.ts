import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import YAML from 'yaml'
import { describe, expect, it } from 'vitest'
import { createCandidateRule, seedCollectors } from './fixtures'

const contracts = resolve(process.cwd(), '../docs/contracts')
const openapi = YAML.parse(readFileSync(resolve(contracts, 'openapi.yaml'), 'utf8'))
const gatherSpecSchema = JSON.parse(readFileSync(resolve(contracts, 'gather-spec.schema.json'), 'utf8'))

describe('frozen machine contracts', () => {
  it('pins the browser API to v1 and durable asynchronous commands', () => {
    expect(openapi.openapi).toBe('3.1.0')
    expect(openapi['x-contract-id']).toBe('extrio.control-plane.v1')
    expect(openapi.servers[0].url).toBe('/api/v1')
    expect(openapi.paths['/collectors/{collectorId}/explorations'].post.responses['202'].content['application/json'].schema.$ref).toBe('#/components/schemas/Operation')
    expect(openapi.paths['/collectors/{collectorId}/runs'].post.responses['202'].content['application/json'].schema.$ref).toBe('#/components/schemas/Operation')
    expect(openapi.paths['/collectors/{collectorId}/collection-policy'].post.requestBody.content['application/json'].schema.$ref).toBe('#/components/schemas/CollectionPolicyInput')
    expect(openapi.paths['/collectors/{collectorId}/schedule'].put.requestBody.content['application/json'].schema.$ref).toBe('#/components/schemas/CollectorScheduleInput')
    expect(openapi.components.schemas.CollectorDetail.allOf[1].required).toContain('schedule')
    expect(openapi.components.schemas.OperationStatus.enum).toEqual(['queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out'])
    expect(openapi.components.schemas.Run.required).toContain('operationId')
    expect(openapi.components.schemas.Run.required).toContain('collectionMode')
    expect(openapi.components.schemas.HarvestResult.properties.revision.minimum).toBe(1)
    expect(openapi.components.schemas.HarvestResult.required).toContain('listTitle')
    expect(openapi.components.schemas.HarvestResult.required).toContain('content')
    expect(openapi.components.schemas.HarvestResult.required).toContain('changeType')
    expect(openapi.components.schemas.Run.required).toEqual(expect.arrayContaining(['policyVersion', 'windowStart', 'checkpointBefore', 'checkpointAfter', 'newItems', 'updatedItems', 'unchangedItems']))
    expect(openapi.components.schemas.Operation.allOf).toHaveLength(4)
    expect(openapi.components.schemas.HarvestResult.allOf).toHaveLength(2)
    expect(openapi.components.schemas.CandidateRule.allOf).toHaveLength(2)
  })

  it('validates every prototype GatherSpec against the canonical schema', () => {
    const ajv = new Ajv2020({ allErrors: true, strict: true })
    addFormats(ajv)
    const validate = ajv.compile(gatherSpecSchema)
    const candidates = [
      ...seedCollectors.map((collector) => collector.candidate?.gatherSpec),
      createCandidateRule({
        id: 'collector_single_contract',
        name: '单页公告',
        sourceUrl: 'https://example.gov.cn/single',
        sourceHost: 'example.gov.cn',
        collectionId: 'collection_single_contract',
      }).gatherSpec,
    ].filter(Boolean)

    for (const candidate of candidates) {
      expect(validate(candidate), JSON.stringify(validate.errors, null, 2)).toBe(true)
    }
  })
})
