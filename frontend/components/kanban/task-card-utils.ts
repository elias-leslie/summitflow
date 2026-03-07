import type { Task, TaskStatus } from '@/lib/api'

export const EXECUTION_PHASES = [
  'Triage',
  'Plan',
  'Queue',
  'Execute',
  'Review',
] as const

export type ExecutionPhase = (typeof EXECUTION_PHASES)[number]

export function getPhaseFromStatus(status: TaskStatus): ExecutionPhase | null {
  switch (status) {
    case 'pending':
      return 'Triage'
    case 'paused':
    case 'blocked':
    case 'conflicted':
      return 'Plan'
    case 'queue':
      return 'Queue'
    case 'running':
      return 'Execute'
    case 'ai_reviewing':
      return 'Review'
    default:
      return null
  }
}

export function isCrowdsourcedIdea(task: Task): boolean {
  return (
    task.status === 'pending' &&
    task.labels?.some((label) => label.toLowerCase() === 'crowdsourced')
  )
}
