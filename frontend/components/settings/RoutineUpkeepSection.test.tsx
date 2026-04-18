import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RoutineUpkeepSection } from './RoutineUpkeepSection'

const baseSettings = {
  upkeep_enabled: true,
  upkeep_frequency_minutes: 120,
  upkeep_batch_limit: 5,
}

function makeRun(status: string, tasksCreated: number, dispatched: number) {
  return {
    id: Math.floor(Math.random() * 10000),
    workflow_name: 'routine_upkeep',
    status,
    started_at: '2026-04-10T16:00:00Z',
    finished_at: '2026-04-10T16:01:00Z',
    duration_ms: 60_000,
    rows_cleaned: tasksCreated,
    summary: {
      tasks_created: tasksCreated,
      dispatch: { dispatched },
      created_task_ids: ['task-one', 'task-two'],
    },
    error_message: null,
    created_at: '2026-04-10T16:00:00Z',
  }
}

describe('RoutineUpkeepSection', () => {
  it('disables run now when upkeep is disabled', () => {
    render(
      <RoutineUpkeepSection
        settings={{ ...baseSettings, upkeep_enabled: false }}
        status={{
          settings: { enabled: false, frequency_minutes: 120, batch_limit: 5 },
          latest: null,
          recent: [],
        }}
        isPending={false}
        isRunning={false}
        onEnabledToggle={vi.fn()}
        onFrequencyChange={vi.fn()}
        onBatchLimitChange={vi.fn()}
        onRunNow={vi.fn()}
      />,
    )

    expect(screen.getByText('Disabled')).toBeInTheDocument()
    expect(
      screen.getByRole('switch', { name: 'Enable routine upkeep' }),
    ).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByRole('button', { name: 'Run now' })).toBeDisabled()
  })

  it('summarizes completed work and keeps history compact', () => {
    render(
      <RoutineUpkeepSection
        settings={baseSettings}
        status={{
          settings: { enabled: true, frequency_minutes: 120, batch_limit: 5 },
          latest: makeRun('completed', 2, 2),
          recent: [
            makeRun('completed', 2, 2),
            makeRun('completed', 0, 0),
            makeRun('failed', 0, 0),
            makeRun('completed', 1, 1),
          ],
        }}
        isPending={false}
        isRunning={false}
        onEnabledToggle={vi.fn()}
        onFrequencyChange={vi.fn()}
        onBatchLimitChange={vi.fn()}
        onRunNow={vi.fn()}
      />,
    )

    expect(screen.getByText('Completed · 2 tasks')).toBeInTheDocument()
    expect(document.body).toHaveTextContent(/2\s+created,\s+2\s+dispatched/)
    expect(screen.getAllByText('completed')).toHaveLength(2)
    expect(screen.queryAllByText('failed')).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'Show more' }))
    expect(screen.getAllByText('completed')).toHaveLength(3)
  })

  it('keeps run now visually separate and calls the handler once', () => {
    const onRunNow = vi.fn()
    render(
      <RoutineUpkeepSection
        settings={baseSettings}
        status={{
          settings: { enabled: true, frequency_minutes: 120, batch_limit: 5 },
          latest: null,
          recent: [],
        }}
        isPending={false}
        isRunning={false}
        onEnabledToggle={vi.fn()}
        onFrequencyChange={vi.fn()}
        onBatchLimitChange={vi.fn()}
        onRunNow={onRunNow}
      />,
    )

    expect(screen.getByText('Never run')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Run now' }))
    expect(onRunNow).toHaveBeenCalledOnce()
  })
})
