import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ResumeBar } from './ResumeBar'

const sonnerMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: sonnerMocks,
}))

describe('ResumeBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn(),
    }) as unknown as typeof fetch
  })

  it('re-queues the task for the provided project id', async () => {
    render(
      <ResumeBar
        projectId="agent-hub"
        taskId="task-123"
        personaName="Jenny"
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /re-run task/i }))

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:8001/api/projects/agent-hub/tasks/task-123/execute',
        expect.objectContaining({
          method: 'POST',
        }),
      )
    })

    expect(sonnerMocks.success).toHaveBeenCalledWith('Task re-queued', {
      description: 'Jenny will retry this task with your guidance',
    })
  })
})
