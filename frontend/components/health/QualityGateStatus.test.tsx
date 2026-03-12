import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { QualityGateStatus } from './QualityGateStatus'

describe('QualityGateStatus', () => {
  it('renders a no-data state when no summary is available', () => {
    render(<QualityGateStatus health={undefined} />)

    expect(screen.getByText('No quality runs have been recorded for this project yet.')).toBeInTheDocument()
    expect(screen.getByText('No data')).toBeInTheDocument()
  })

  it('shows overall health, open issue count, and per-check freshness', () => {
    render(
      <QualityGateStatus
        health={{
          project_id: 'summitflow',
          overall_pass: false,
          total_unfixed: 3,
          checks: {
            ruff: {
              status: 'fail',
              error_count: 3,
              warning_count: 0,
              last_run: '2026-03-12T09:00:00Z',
            },
            types: {
              status: 'pass',
              error_count: 0,
              warning_count: 1,
              last_run: '2026-03-12T09:05:00Z',
            },
          },
        }}
      />,
    )

    expect(screen.getByText('Failing')).toBeInTheDocument()
    expect(screen.getByText('3 open')).toBeInTheDocument()
    expect(screen.getByText('Ruff')).toBeInTheDocument()
    expect(screen.getByText('3 errors')).toBeInTheDocument()
    expect(screen.getByText('Types')).toBeInTheDocument()
    expect(screen.getByText('1 warning')).toBeInTheDocument()
    expect(screen.getByText(/Last run/)).toBeInTheDocument()
  })
})
