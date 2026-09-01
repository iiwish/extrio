import { describe, expect, it } from 'vitest'
import { collectorStage, statusLabel, statusTone } from './status'

describe('status contract', () => {
  it('keeps Collector progress deterministic', () => {
    expect(collectorStage('draft', false)).toBe(0)
    expect(collectorStage('ready_review', false)).toBe(2)
    expect(collectorStage('published', false)).toBe(3)
    expect(collectorStage('published', true)).toBe(4)
  })

  it('does not encode status through color alone', () => {
    expect(statusLabel('partially_succeeded')).toBe('部分成功')
    expect(statusTone('partially_succeeded')).toBe('warning')
    expect(statusLabel('rejected')).toBe('已拒绝')
  })
})
