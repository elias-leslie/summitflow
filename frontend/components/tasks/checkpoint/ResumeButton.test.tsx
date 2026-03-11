import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ResumeButton } from './ResumeButton'

const sonnerMocks = vi.hoisted(() => ({
  error: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: sonnerMocks,
}))

describe('ResumeButton', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ resume_prompt: 'Resume from checkpoint' }),
      }),
    )
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    })
  })

  it('copies the fetched resume prompt on the first click', async () => {
    const onResume = vi.fn()

    render(
      <ResumeButton
        checkpointId="cp-123"
        projectId="summitflow"
        onResume={onResume}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Copy Resume Prompt' }))

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8001/api/projects/summitflow/checkpoints/cp-123/resume',
        { method: 'POST' },
      )
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        'Resume from checkpoint',
      )
      expect(onResume).toHaveBeenCalledWith('Resume from checkpoint')
    })
  })

  it('shows a toast when fetching the prompt fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ detail: 'Request failed' }),
      }),
    )

    render(<ResumeButton checkpointId="cp-123" projectId="summitflow" />)

    fireEvent.click(screen.getByRole('button', { name: 'Copy Resume Prompt' }))

    await waitFor(() => {
      expect(sonnerMocks.error).toHaveBeenCalledWith(
        'Failed to load resume prompt',
      )
    })
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled()
  })
})
