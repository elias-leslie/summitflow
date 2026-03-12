import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FixPipelineCard } from './FixPipelineCard'

describe('FixPipelineCard', () => {
  it('shows an empty state when no quality findings were detected', () => {
    render(
      <FixPipelineCard
        detected={0}
        flashFixed={0}
        sonnetFixed={0}
        escalatedCount={0}
        autoFixRate={0}
      />,
    )

    expect(screen.getByText('No quality detections this week')).toBeInTheDocument()
  })

  it('shows unresolved issue counts alongside resolved percentages', () => {
    render(
      <FixPipelineCard
        detected={10}
        flashFixed={3}
        sonnetFixed={2}
        escalatedCount={1}
        autoFixRate={50}
      />,
    )

    expect(screen.getByText('Still Open')).toBeInTheDocument()
    expect(screen.getByText('4 (40%)')).toBeInTheDocument()
    expect(screen.getByText('3 (30%)')).toBeInTheDocument()
    expect(screen.getByText('50% auto-resolved')).toBeInTheDocument()
    expect(screen.getByText('Manual Follow-up')).toBeInTheDocument()
  })
})
