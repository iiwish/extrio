import { describe, expect, it } from 'vitest'
import { readableContent, runTimestamp } from './content-presentation'

describe('safe content presentation', () => {
  it('preserves plain text including comparison symbols', () => {
    expect(readableContent('Budget < 200\nA & B')).toEqual({ text: 'Budget < 200\nA & B', isHtml: false })
  })
  it('extracts inert readable text with paragraph boundaries, not scripts or hidden content', () => {
    const result = readableContent('<div><p>Notice &amp; details</p><p>Amount: 100</p><script>alert(1)</script><span hidden>Hidden</span><span style="display: none">Wrong title</span><img src="https://example.com/tracker" onerror="alert(2)"></div>')
    expect(result).toEqual({ text: 'Notice & details\nAmount: 100', isHtml: true })
  })
  it('formats the persisted timestamp instead of a stale relative display label', () => {
    expect(runTimestamp({ startedAtIso:'2026-09-01T00:00:00Z', startedAt:'刚刚' }, 'en')).not.toBe('刚刚')
    expect(runTimestamp({ startedAt:'2026-09-01 10:00' }, 'en')).toBe('2026-09-01 10:00')
  })
})
