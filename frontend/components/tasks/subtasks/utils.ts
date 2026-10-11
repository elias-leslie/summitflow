import type { Step, Subtask } from '@/lib/api/tasks'

export function groupByPhase(subtasks: Subtask[]): Record<string, Subtask[]> {
  return subtasks.reduce(
    (acc, subtask) => {
      const phase = subtask.phase || 'other'
      if (!acc[phase]) acc[phase] = []
      acc[phase].push(subtask)
      return acc
    },
    {} as Record<string, Subtask[]>,
  )
}

export function getStepInfo(subtask: Subtask) {
  if (subtask.step_summary) {
    return {
      total: subtask.step_summary.total,
      completed: subtask.step_summary.completed,
    }
  }
  if (subtask.steps_from_table?.length) {
    const completed = subtask.steps_from_table.filter((s) => s.passes).length
    return { total: subtask.steps_from_table.length, completed }
  }
  if (subtask.steps?.length) {
    return { total: subtask.steps.length, completed: 0 }
  }
  return null
}

export type DisplayStep = Pick<
  Step,
  'step_number' | 'description' | 'passes' | 'spec'
>

function toDisplayStep(raw: unknown, index: number): DisplayStep | null {
  if (typeof raw === 'string') {
    return raw.trim()
      ? { step_number: index + 1, description: raw, passes: false, spec: null }
      : null
  }
  if (!raw || typeof raw !== 'object') return null
  const step = raw as Partial<Step>
  if (typeof step.description !== 'string' || !step.description.trim()) {
    return null
  }
  return {
    step_number:
      typeof step.step_number === 'number' ? step.step_number : index + 1,
    description: step.description,
    passes: step.passes === true,
    spec: step.spec ?? null,
  }
}

/** Steps arrive on the subtask payload: table steps first, else plan-context steps. */
export function getDisplaySteps(subtask: Subtask): DisplayStep[] {
  const source: unknown[] = subtask.steps_from_table?.length
    ? subtask.steps_from_table
    : (subtask.steps ?? [])
  return source
    .map(toDisplayStep)
    .filter((step): step is DisplayStep => step !== null)
}
