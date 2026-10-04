import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DevelopmentProjection } from '@/lib/api/git'
import { development, repo, sourceSha } from './developmentFixtures'
import { ProjectRow } from './ProjectRow'

const api = vi.hoisted(() => ({
  publishProjectChanges: vi.fn(),
  pullRepository: vi.fn(),
  checkProjectGitRemote: vi.fn(),
}))
vi.mock('@/lib/api/git', () => api)
vi.mock('./project-row/DashboardContent', () => ({
  DashboardContent: ({ projectId }: { projectId: string }) => (
    <div>{projectId} history</div>
  ),
}))
function renderRow(value: DevelopmentProjection = development) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ProjectRow repo={repo} development={value} />
    </QueryClientProvider>,
  )
}
function openActions() {
  fireEvent.click(screen.getByText('Publication and remote actions'))
}
beforeEach(() => vi.clearAllMocks())
describe('Development repository', () => {
  it('shows neutral local work separately from acceptance and runtime drift', () => {
    renderRow()
    expect(screen.getByText('2 uncommitted files')).toBeInTheDocument()
    expect(screen.getByText(/1 unpublished commit against/)).toBeInTheDocument()
    expect(screen.getByText('Source drift')).toBeInTheDocument()
    expect(screen.queryByText('Dirty')).not.toBeInTheDocument()
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
    openActions()
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
  it('disables publication for stale acceptance while preserving history', () => {
    renderRow({
      ...development,
      accepted: { ...development.accepted, state: 'stale', drift: true },
    })
    openActions()
    expect(
      screen.getByRole('button', { name: 'Publish accepted source' }),
    ).toBeDisabled()
    fireEvent.click(screen.getByText('Branches, checkpoints and history'))
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
    openActions()
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
    expect(screen.getByText('Task store unavailable')).toBeInTheDocument()
    expect(
      screen.queryByText('No blocked or failed tasks recorded'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Repair deployment' }),
    ).toHaveAttribute('href', '/projects/project-alpha?tab=tasks&task=task-123')
  })
})
