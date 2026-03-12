// Types for Health Tab API responses

export type QualityCheckStatus =
  | 'pass'
  | 'passing'
  | 'fail'
  | 'error'
  | 'skipped'
  | 'warning'
  | 'unknown'

export interface HealthCheckSummary {
  status: QualityCheckStatus | string
  error_count: number
  warning_count: number
  last_run: string
}

export interface HealthSummary {
  project_id: string
  overall_pass: boolean
  total_unfixed: number
  checks: Record<string, HealthCheckSummary>
}

export interface CheckResult {
  id: number
  project_id: string
  check_type: string
  check_name: string | null
  status: string
  error_count: number
  warning_count: number
  error_message: string | null
  file_path: string | null
  line_number: number | null
  column_number: number | null
  run_duration_ms: number | null
  git_sha: string | null
  triggered_by: string | null
  fix_attempted: boolean
  fix_attempts: number
  fixed_at: string | null
  fixed_by: string | null
  created_at: string
  updated_at: string
  escalation_task_id: string | null
}

export interface CheckResultsResponse {
  items: CheckResult[]
  total: number
  unfixed_count: number
}
