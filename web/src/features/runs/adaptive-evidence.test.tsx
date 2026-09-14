import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import type { AiRunDetail } from '@/api/types'
import { AdaptiveEvidence } from './ai-run-page'

afterEach(cleanup)
const evidence: NonNullable<AiRunDetail['evidence']> = {
  version: 'adaptive-dom-v1', phase: 'failed', limitsSource: 'conservative_default', validated: false,
  budget: { calls: 8, maxCalls: 8, inputTokens: 32000, outputTokens: 4096, maxInputTokens: 120000, maxOutputTokens: 16000, contextTokens: 32768, tokenMethod: 'utf8_upper_estimate', elapsedSeconds: 83, maxSeconds: 240, stopReason: 'MODEL_CALL_BUDGET_EXCEEDED' },
  pages: [{ pageId: 'detail-1', indexedNodes: 251, readNodes: 3, readFragmentChars: 7200 }],
  reads: [{ pageId: 'detail-1', nodeId: 'n50', action: 'read_nodes', digest: 'sha256:test', start: 0, end: 2400, complete: false }],
  validation: [{ code: 'FIELD_MISSING', field: 'content', sample: 1 }],
}

it('shows bounded reads and failure without implying full semantic coverage', () => {
  render(<AdaptiveEvidence value={evidence} showReads />)
  expect(screen.getByText('8 / 8')).toBeInTheDocument()
  expect(screen.getByText('任务已达模型调用上限，未生成验证通过的候选。')).toBeInTheDocument()
  expect(screen.getByText(/UTF-8 保守估算/)).toBeInTheDocument()
  expect(screen.getByText('完整样本尚未验证通过')).toBeInTheDocument()
  expect(screen.getByText('仍有后续')).toBeInTheDocument()
  expect(screen.getByText('样本 1')).toBeInTheDocument()
  expect(screen.queryByText(/100%/)).not.toBeInTheDocument()
})

it('shows successful full-sample validation without the read log in process view', () => {
  render(<AdaptiveEvidence value={{ ...evidence, phase: 'validated', validated: true, budget: { ...evidence.budget, stopReason: null }, validation: [] }} />)
  expect(screen.getByText('完整样本验证通过')).toBeInTheDocument()
  expect(screen.queryByText('n50')).not.toBeInTheDocument()
  expect(screen.queryByText('已停止')).not.toBeInTheDocument()
})

it.each([
  ['MODEL_DISCOVERY_BUDGET_EXCEEDED', '规则发现阶段额度已用尽，后续编译额度仍保留。请补充来源说明后重试。'],
  ['MODEL_NO_PROGRESS', '重复调用或验证纠错持续无进展，已停止尝试。请检查来源说明和验证反馈。'],
])('explains %s without claiming the whole call budget was spent', (stopReason, message) => {
  render(<AdaptiveEvidence value={{ ...evidence, budget: { ...evidence.budget, calls: 4, maxCalls: 16, stopReason } }} />)
  expect(screen.getByText('4 / 16')).toBeInTheDocument()
  expect(screen.getByText(message)).toBeInTheDocument()
  expect(screen.getByText('完整样本尚未验证通过')).toBeInTheDocument()
})
