import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CheckResult } from './HealthTypes'
import { NeedsAttentionCard } from './NeedsAttentionCard'

let nextId = 1

function createMockQualityCheck(overrides: Partial<CheckResult> = {}): CheckResult {
  const id = nextId++
  return {
    id,
    project_id: 'summitflow',
    check_type: 'ruff',
    check_name: 'Ruff',
    status: 'failed',
    error_count: 1,
    warning_count: 0,
    error_message: null,
    file_path: `/repo/file_${id}.py`,
    line_number: id * 10,
    column_number: null,
    run_duration_ms: null,
    git_sha: null,
    triggered_by: null,
    fix_attempted: false,
    fix_attempts: 0,
    fixed_at: null,
    fixed_by: null,
    created_at: '2026-03-11T12:00:00Z',
    updated_at: '2026-03-11T12:00:00Z',
    escalation_task_id: null,
    ...overrides,
  }
}

describe('NeedsAttentionCard', () => {
  it('surfaces escalated issues and hidden overflow counts', () => {
    nextId = 1
    render(
      <NeedsAttentionCard
        items={[
          createMockQualityCheck({
            id: 1,
            check_type: 'ruff',
            check_name: 'Ruff',
            error_count: 3,
            file_path: '/repo/frontend/app/page.tsx',
            line_number: 14,
            fix_attempted: true,
            fix_attempts: 2,
            escalation_task_id: 'task-123',
          }),
          createMockQualityCheck({
            id: 2,
            check_type: 'types',
            check_name: 'Types',
            file_path: '/repo/frontend/components/health/FixPipelineCard.tsx',
            line_number: 22,
          }),
          createMockQualityCheck({
            id: 3,
            check_type: 'pytest',
            check_name: 'Pytest',
            file_path: '/repo/backend/tests/api/test_projects.py',
            line_number: 48,
          }),
          createMockQualityCheck({
            id: 4,
            check_type: 'biome',
            check_name: 'Biome',
            file_path: '/repo/frontend/components/dashboard/ProjectCard.tsx',
            line_number: 77,
          }),
          createMockQualityCheck({
            id: 5,
            check_type: 'sqlfluff',
            check_name: 'SQLFluff',
            file_path: '/repo/backend/alembic/versions/demo.py',
            line_number: 11,
          }),
          createMockQualityCheck({
            id: 6,
            check_type: 'ruff',
            check_name: 'Ruff',
            file_path: '/repo/backend/app/main.py',
            line_number: 90,
          }),
        ]}
      />,
    )

    expect(screen.getByText('Escalated')).toBeInTheDocument()
    expect(screen.getByText('+1 more unresolved issues')).toBeInTheDocument()
    expect(screen.getByText('app/page.tsx')).toBeInTheDocument()
  })

  it('renders the all-clear state for an empty array', () => {
    render(<NeedsAttentionCard items={[]} />)

    expect(screen.getByText('All Clear')).toBeInTheDocument()
    expect(screen.queryByText('Needs Attention')).not.toBeInTheDocument()
  })

  it('marks every item as Escalated when all have escalation task ids', () => {
    nextId = 100
    render(
      <NeedsAttentionCard
        items={[
          createMockQualityCheck({ escalation_task_id: 'task-a' }),
          createMockQualityCheck({ escalation_task_id: 'task-b' }),
        ]}
      />,
    )

    const escalatedBadges = screen.getAllByText('Escalated')
    expect(escalatedBadges).toHaveLength(2)
  })

  it('does not render an overflow line when items fit within the visible limit', () => {
    nextId = 200
    render(
      <NeedsAttentionCard
        items={[
          createMockQualityCheck(),
          createMockQualityCheck(),
          createMockQualityCheck(),
        ]}
      />,
    )

    expect(screen.queryByText(/more unresolved/)).not.toBeInTheDocument()
  })
})
