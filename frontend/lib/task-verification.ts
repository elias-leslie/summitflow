import type { VerificationResult } from './api/tasks'

const TRUSTED_VERIFICATION_SOURCES = new Set([
  'autonomous_quality_gate',
  'autonomous_preverified_subtasks',
])

function isNonNegativeNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
}

function isFabricatedZeroCountSummary(result: VerificationResult): boolean {
  return (
    result.all_verified === true && result.total === 0 && result.verified === 0
  )
}

function isHistoricAutonomousResult(result: VerificationResult): boolean {
  return (
    typeof result.execution_clean === 'boolean' &&
    isNonNegativeNumber(result.subtask_count) &&
    isNonNegativeNumber(result.total_self_fix_attempts) &&
    isNonNegativeNumber(result.total_supervisor_attempts)
  )
}

/**
 * Return true only when a verification result represents real autonomous evidence.
 *
 * Current pipeline payloads carry an explicit marker and trusted source. Historic
 * autonomous payloads predate those fields, so their complete metric shape remains
 * accepted. The former completion-time zero-count summary is explicitly rejected.
 */
export function hasVerifiedEvidence(
  result: VerificationResult | null | undefined,
): boolean {
  if (!result || isFabricatedZeroCountSummary(result)) return false

  const hasExplicitAttestation =
    result.evidence_verified !== undefined ||
    result.verification_source !== undefined
  if (hasExplicitAttestation) {
    return (
      result.evidence_verified === true &&
      typeof result.verification_source === 'string' &&
      TRUSTED_VERIFICATION_SOURCES.has(result.verification_source)
    )
  }

  return isHistoricAutonomousResult(result)
}
