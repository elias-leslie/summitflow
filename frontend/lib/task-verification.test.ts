import { describe, expect, it } from 'vitest'
import { hasVerifiedEvidence } from './task-verification'

describe('hasVerifiedEvidence', () => {
  it('rejects the former zero-count completion summary', () => {
    expect(
      hasVerifiedEvidence({
        total: 0,
        verified: 0,
        unverified: [],
        all_verified: true,
      }),
    ).toBe(false)
  })

  it('accepts current autonomous quality-gate evidence', () => {
    expect(
      hasVerifiedEvidence({
        evidence_verified: true,
        verification_source: 'autonomous_quality_gate',
        execution_clean: true,
        subtask_count: 0,
        total_self_fix_attempts: 0,
        total_supervisor_attempts: 0,
      }),
    ).toBe(true)
  })

  it('rejects explicit attestations from unknown sources', () => {
    expect(
      hasVerifiedEvidence({
        evidence_verified: true,
        verification_source: 'manual_completion',
        execution_clean: true,
        subtask_count: 1,
        total_self_fix_attempts: 0,
        total_supervisor_attempts: 0,
      }),
    ).toBe(false)
  })

  it('accepts the complete historic autonomous metric shape', () => {
    expect(
      hasVerifiedEvidence({
        execution_clean: false,
        subtask_count: 2,
        total_self_fix_attempts: 1,
        total_supervisor_attempts: 0,
      }),
    ).toBe(true)
  })
})
