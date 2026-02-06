import type { Subtask } from '@/lib/api/tasks'

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
