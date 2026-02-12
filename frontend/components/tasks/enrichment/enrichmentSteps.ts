import {
  FolderSearch,
  Layers,
  Target,
  ListChecks,
  ShieldCheck,
} from 'lucide-react'
import type { Task } from '@/lib/api/tasks'
import type { ProgressStep, StepStatus } from './types'

// Simulate enrichment progress based on elapsed time
// In reality, the backend would provide step-by-step updates
export function estimateSteps(task: Task, elapsedMs: number): ProgressStep[] {
  const stepDuration = 4000 // Estimate ~4s per step

  const getStatus = (stepIndex: number): StepStatus => {
    const stepStart = stepIndex * stepDuration
    if (elapsedMs >= stepStart + stepDuration) return 'completed'
    if (elapsedMs >= stepStart) return 'active'
    return 'pending'
  }

  // Extract some info from the task if available
  const criteriaCount = task.acceptance_criteria?.length ?? 0

  return [
    {
      id: 'context',
      label: 'Gathering context from codebase...',
      completedLabel: 'Found relevant files and patterns',
      icon: FolderSearch,
      status: getStatus(0),
    },
    {
      id: 'analysis',
      label: 'Analyzing codebase patterns...',
      completedLabel: 'Analysis complete',
      icon: Layers,
      status: getStatus(1),
    },
    {
      id: 'objective',
      label: 'Generating objective...',
      completedLabel: 'Objective defined',
      icon: Target,
      status: getStatus(2),
    },
    {
      id: 'criteria',
      label: 'Creating acceptance criteria...',
      completedLabel:
        criteriaCount > 0
          ? `Generated ${criteriaCount} criteria`
          : 'Generating criteria',
      icon: ListChecks,
      status: getStatus(3),
    },
    {
      id: 'subtasks',
      label: 'Building implementation subtasks...',
      completedLabel: 'Subtasks created',
      icon: ListChecks,
      status: getStatus(4),
    },
    {
      id: 'validation',
      label: 'Cross-validating with Gemini...',
      completedLabel: 'Validation complete',
      icon: ShieldCheck,
      status: getStatus(5),
    },
  ]
}
