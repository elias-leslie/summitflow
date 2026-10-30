import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { VerificationResult } from '@/lib/api/tasks-types-core'
import {
  CloseoutSection,
  latestPauseReason,
  PauseReason,
  readCloseout,
  TaskHistory,
} from './TaskHistory'

const api = vi.hoisted(() => ({ getEventsForTrace: vi.fn() }))
vi.mock('@/lib/api/events', () => api)

function wrap(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>{node}</QueryClientProvider>,
  )
}

const event = (message: string, timestamp: string, level = 'info') => ({
  id: `${timestamp}-${message}`,
  message,
  timestamp,
  level,
})

beforeEach(() => vi.clearAllMocks())

describe('task history', () => {
  it('reads the task events as user history, newest first', async () => {
    api.getEventsForTrace.mockResolvedValue([
      event('Claimed by cc:abc', '2026-10-29T10:00:00Z'),
      event('Local closeout cleanup completed.', '2026-10-29T11:00:00Z'),
    ])
    wrap(<TaskHistory projectId="summitflow" taskId="task-1" />)
    expect(
      await screen.findByText('Local closeout cleanup completed.'),
    ).toBeInTheDocument()
    expect(api.getEventsForTrace).toHaveBeenCalledWith('summitflow', 'task-1', {
      visibility: 'user',
      limit: 1000,
    })
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items[0]).toContain('Local closeout cleanup completed.')
  })

  it('skips events without a message', async () => {
    api.getEventsForTrace.mockResolvedValue([
      { ...event('', '2026-10-29T09:00:00Z'), message: null },
      event('Claimed', '2026-10-29T10:00:00Z'),
    ])
    wrap(<TaskHistory projectId="p" taskId="t" />)
    await screen.findByText('Claimed')
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
  })

  it('says when nothing is recorded and when loading failed', async () => {
    api.getEventsForTrace.mockResolvedValueOnce([])
    const { unmount } = wrap(<TaskHistory projectId="p" taskId="t" />)
    expect(
      await screen.findByText('Nothing recorded on this task.'),
    ).toBeInTheDocument()
    unmount()
    api.getEventsForTrace.mockRejectedValueOnce(new Error('down'))
    wrap(<TaskHistory projectId="p" taskId="t" />)
    expect(
      await screen.findByText('Could not load the task history.'),
    ).toBeInTheDocument()
  })
})

describe('pause reason', () => {
  it('takes the reason from the last pause', () => {
    expect(
      latestPauseReason([
        event('Paused: first', '2026-10-01T00:00:00Z'),
        event('Reopened: retry', '2026-10-02T00:00:00Z'),
        event('Paused: waiting on the owner', '2026-10-03T00:00:00Z'),
        event('progress note', '2026-10-04T00:00:00Z'),
      ]),
    ).toEqual({ reason: 'waiting on the owner', at: '2026-10-03T00:00:00Z' })
    expect(
      latestPauseReason([event('progress', '2026-10-01T00:00:00Z')]),
    ).toBeNull()
    // A reason followed by a reopen belongs to an earlier pause; the current one gave none.
    expect(
      latestPauseReason([
        event('Paused: old reason', '2026-10-01T00:00:00Z'),
        event('Reopened: try again', '2026-10-02T00:00:00Z'),
      ]),
    ).toBeNull()
  })

  it('shows the reason, or says none was given', async () => {
    api.getEventsForTrace.mockResolvedValueOnce([
      event('Paused: Blocked on the gh token', '2026-10-25T00:39:34Z'),
    ])
    const { unmount } = wrap(<PauseReason projectId="p" taskId="t" />)
    expect(
      await screen.findByText('Blocked on the gh token'),
    ).toBeInTheDocument()
    unmount()
    api.getEventsForTrace.mockResolvedValueOnce([])
    wrap(<PauseReason projectId="p" taskId="t" />)
    expect(
      await screen.findByText('No reason was given when it was paused.'),
    ).toBeInTheDocument()
  })
})

describe('closeout', () => {
  const result = {
    closeout: {
      kind: 'local_closeout.v1',
      message: 'Root cause fixed in 075bdebd9',
      source_sha: '00870430689ba54604591af5b39fc94d0ee92a85',
      paths: ['backend/cli/lib/coord.py', 'scripts/lib/lease-hook'],
    },
    acceptance: { outcome: 'pass', coverage: 'full', check_count: 12 },
  } as unknown as VerificationResult

  it('shows the st done summary, source commit, files and acceptance', () => {
    render(<CloseoutSection result={result} />)
    expect(screen.getByText('How it was finished')).toBeInTheDocument()
    expect(
      screen.getByText('Root cause fixed in 075bdebd9'),
    ).toBeInTheDocument()
    expect(screen.getByText('008704306')).toBeInTheDocument()
    expect(screen.getByText('scripts/lib/lease-hook')).toBeInTheDocument()
    expect(screen.getByText('Passed (12 checks), full run')).toBeInTheDocument()
  })

  it('stays away when no closeout was recorded', () => {
    expect(readCloseout({ subtask_count: 2 })).toBeNull()
    expect(readCloseout(null)).toBeNull()
    const { container } = render(
      <CloseoutSection result={{ subtask_count: 2 }} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
