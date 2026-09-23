import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBadge } from './StatusBadge'

describe('Backup status badge', () => {
  it('shows a confirmed cancelled capture without calling it failed', () => {
    render(
      <StatusBadge
        status="failed"
        activity={{ phase: 'cancelled', active: false }}
      />,
    )
    expect(screen.getByText('cancelled')).toHaveClass('text-slate-400')
    expect(screen.queryByText('failed')).not.toBeInTheDocument()
  })

  it('keeps a completed local backup completed if its later Drive sync was cancelled', () => {
    render(
      <StatusBadge
        status="completed"
        activity={{ phase: 'cancelled', active: false }}
      />,
    )
    expect(screen.getByText('completed')).toBeInTheDocument()
  })

  it('does not present an active cancellation request as cancelled', () => {
    render(
      <StatusBadge
        status="running"
        activity={{ phase: 'capture', active: true }}
      />,
    )
    expect(screen.getByText('running')).toBeInTheDocument()
  })

  it('preserves genuine failures and legacy status without activity metadata', () => {
    render(<StatusBadge status="failed" />)
    expect(screen.getByText('failed')).toHaveClass('text-red-400')
  })
})
