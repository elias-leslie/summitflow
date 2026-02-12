// Types for Pipeline Health API responses

export interface TaskDistribution {
  pending: number
  queue: number
  running: number
  ai_reviewing: number
  completed: number
  blocked: number
  failed: number
  cancelled: number
  abandoned: number
}

export interface Throughput {
  completed_today: number
  completed_this_week: number
  avg_completion_hours: number
}

export interface SelfHealing {
  first_attempt_pass_rate: number
  avg_self_fix_attempts: number
  supervisor_escalation_rate: number
  model_escalation_count: number
}

export interface Verification {
  step_pass_rate: number
  avg_retries_per_step: number
}

export interface PartialMerge {
  full_completion_rate: number
  partial_completion_rate: number
  total_failure_rate: number
}

export interface Autonomous {
  running_count: number
  max_concurrent: number
  queue_depth: number
  next_scheduled: string | null
}

export interface PipelineStatsResponse {
  task_distribution: TaskDistribution
  throughput: Throughput
  self_healing: SelfHealing
  verification: Verification
  partial_merge: PartialMerge
  autonomous: Autonomous
}
