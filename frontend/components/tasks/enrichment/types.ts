import type { Task } from '@/lib/api/tasks'

export interface EnrichmentProgressProps {
  projectId: string
  task: Task
  onComplete: (task: Task) => void
  onError: (error: string) => void
}

export type StepStatus = 'pending' | 'active' | 'completed'

export interface ProgressStep {
  id: string
  label: string
  completedLabel?: string
  icon: React.ElementType
  status: StepStatus
}
