import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BlockedTasksAlert } from './BlockedTasksAlert'

const fetchBlockedTasksMock = vi.fn()

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api')
  return {
    ...actual,
    fetchBlockedTasks: (...args: unknown[]) => fetchBlockedTasksMock(...args),
    updateTaskStatus: vi.fn(),
  }
})

vi.mock('@/lib/task-mutation-sync', () => ({
  useTaskMutationSync: () => ({
    syncUpdatedTask: vi.fn(),
  }),
}))

function renderAlert() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <BlockedTasksAlert projectId="summitflow" />
    </QueryClientProvider>,
  )
}

describe('BlockedTasksAlert', () => {
  it('shows a recoverable error state when blocked tasks fail to load', async () => {
    fetchBlockedTasksMock.mockRejectedValue(new Error('task API offline'))

    renderAlert()

    await waitFor(() => {
      expect(screen.getByText('Blocked task status unavailable')).toBeInTheDocument()
    })

    expect(screen.getByText('task API offline')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})
