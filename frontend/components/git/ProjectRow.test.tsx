import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DevelopmentProjection, RepoStatus } from '@/lib/api/git'
import { development, repo, sourceSha } from './developmentFixtures'
import { ProjectRow } from './ProjectRow'

const api = vi.hoisted(() => ({
  publishProjectChanges: vi.fn(),
  pullRepository: vi.fn(),
  checkProjectGitRemote: vi.fn(),
}))
vi.mock('@/lib/api/git', () => api)
vi.mock('@/components/snapshots/SavedWorkEvidence', () => ({
  SavedWorkEvidence: () => <span>saved edits</span>,
}))
vi.mock('./project-row/DashboardContent', () => ({
  DashboardContent: ({ projectId }: { projectId: string }) => (
    <div>{projectId} history</div>
  ),
}))
function renderRow(
  value: DevelopmentProjection = development,
  status: RepoStatus = repo,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ProjectRow repo={status} development={value} />
    </QueryClientProvider>,
  )
}
function expand() {
  fireEvent.click(screen.getByRole('button', { name: /alpha/ }))
}
beforeEach(() => vi.clearAllMocks())
describe('Development repository row', () => {
  it('summarizes each stage in one collapsed row without loading details', () => {
    renderRow()
    expect(screen.getByText('2 files')).toBeInTheDocument()
    expect(screen.getByText('↑1')).toBeInTheDocument()
    expect(screen.getByText('bbbbbbb')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /alpha/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(screen.queryByText('saved edits')).not.toBeInTheDocument()
    expect(api.publishProjectChanges).not.toHaveBeenCalled()
    expect(api.checkProjectGitRemote).not.toHaveBeenCalled()
  })
  it('publishes the full accepted SHA and retains the result', async () => {
    api.publishProjectChanges.mockResolvedValue({
      status: 'success',
      publication_complete: true,
      evidence_recorded: true,
      pushed: true,
      requested_source_commit: sourceSha,
    })
    renderRow()
    expand()
    fireEvent.click(
      screen.getByRole('button', { name: 'Publish accepted source' }),
    )
    await waitFor(() =>
      expect(api.publishProjectChanges).toHaveBeenCalledWith(
        'project-alpha',
        sourceSha,
      ),
    )
    expect(await screen.findByText('Publication complete')).toBeInTheDocument()
  })
  it('offers a quick publish only for manual publication of accepted source', () => {
    renderRow({
      ...development,
      publication: { ...development.publication, mode: 'manual' },
    })
    expect(
      screen.getByRole('button', { name: 'Publish alpha' }),
    ).toBeInTheDocument()
  })
  it('disables publication for stale acceptance and loads history on demand', () => {
    renderRow({
      ...development,
      accepted: { ...development.accepted, state: 'stale', drift: true },
    })
    expand()
    expect(
      screen.getByRole('button', { name: 'Publish accepted source' }),
    ).toBeDisabled()
    expect(screen.queryByText('project-alpha history')).not.toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'Commits, branches and checkpoints' }),
    )
    expect(screen.getByText('project-alpha history')).toBeVisible()
  })
  it('reports pull and publication failures', async () => {
    api.pullRepository.mockResolvedValue({
      results: [
        {
          path: repo.path,
          name: repo.name,
          status: 'skipped',
          reason: 'uncommitted changes',
        },
      ],
    })
    api.publishProjectChanges.mockRejectedValue(
      new Error('Publication unavailable'),
    )
    renderRow()
    expand()
    fireEvent.click(screen.getByRole('button', { name: 'Pull remote changes' }))
    expect(
      await screen.findByText(/alpha: skipped: uncommitted changes/),
    ).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'Publish accepted source' }),
    )
    expect(
      await screen.findByText('Publication unavailable'),
    ).toBeInTheDocument()
  })
  it('keeps unavailable blockers distinct from an empty queue and links actual task routes', () => {
    renderRow({
      ...development,
      blockers: {
        state: 'unavailable',
        reason: 'Task store unavailable',
        items: [
          {
            task_id: 'task-123',
            title: 'Repair deployment',
            status: 'blocked',
            reason: 'Runtime observation failed',
          },
        ],
      },
    })
    expect(screen.getByText('unknown')).toBeInTheDocument()
    expand()
    expect(screen.getByText('Task store unavailable')).toBeInTheDocument()
    expect(
      screen.queryByText('No blocked or failed tasks'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Repair deployment' }),
    ).toHaveAttribute('href', '/projects/project-alpha?tab=tasks&task=task-123')
  })
})
