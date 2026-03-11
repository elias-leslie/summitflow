import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
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

  it('uses the cached prompt on subsequent clicks without fetching again', async () => {
    render(<ResumeButton checkpointId="cp-123" projectId="summitflow" />)

    fireEvent.click(screen.getByRole('button', { name: 'Copy Resume Prompt' }))
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1)
    })

    // Button briefly shows "Copied!" then reverts — click again after it reverts
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Copy Resume Prompt' })).toBeInTheDocument()
    }, { timeout: 3000 })

    fireEvent.click(screen.getByRole('button', { name: 'Copy Resume Prompt' }))
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(2)
    })

    // fetch must only have been called once — the second click reused the cached prompt
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('shows a toast when the clipboard write throws', async () => {
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText: vi.fn().mockRejectedValue(new Error('Clipboard denied')),
      },
    })

    render(<ResumeButton checkpointId="cp-123" projectId="summitflow" />)

    fireEvent.click(screen.getByRole('button', { name: 'Copy Resume Prompt' }))

    await waitFor(() => {
      expect(sonnerMocks.error).toHaveBeenCalledWith('Clipboard denied')
    })
  })

  it('shows a toast when the network request throws', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Network error')),
    )

    render(<ResumeButton checkpointId="cp-123" projectId="summitflow" />)

    fireEvent.click(screen.getByRole('button', { name: 'Copy Resume Prompt' }))

    await waitFor(() => {
      expect(sonnerMocks.error).toHaveBeenCalledWith('Network error')
    })
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled()
  })
})
