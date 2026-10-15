import { describe, expect, it } from 'vitest'
import type { VerificationResult } from '@/lib/api/tasks-types-core'
import { executionSummary, hasExecutionFacts } from './TaskModalContent'

describe('Completion gate summary', () => {
  it('hides the gate for sparse publication-repair results', () => {
    const sparse = { publication_repair: { codeql: {} } } as VerificationResult
    expect(hasExecutionFacts(sparse)).toBe(false)
  })

  it('reports only recorded execution facts', () => {
    expect(executionSummary({ subtask_count: 1 })).toBe('1 subtask executed')
    expect(executionSummary({ subtask_count: 3 })).toBe('3 subtasks executed')
    expect(executionSummary({ execution_clean: false })).toBe(
      'Subtask count not recorded',
    )
    expect(executionSummary({ execution_clean: true })).toBe('Clean execution')
    expect(executionSummary({ partial_merge: true })).toBe('Partial merge')
    expect(
      executionSummary({
        partial_merge: true,
        passed_count: 2,
        subtask_count: 3,
      }),
    ).toBe('Partial merge — 2/3 subtasks passed')
  })
})
