import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RuntimeHealthCounts } from './RuntimeHealthCounts'

describe('RuntimeHealthCounts', () => {
  it('shows running services so running and stopped add up to the total', () => {
    render(
      <RuntimeHealthCounts
        health={{
          total: 35,
          healthy: 11,
          unhealthy: 0,
          running: 20,
          stopped: 15,
        }}
      />,
    )

    expect(screen.getByText('35 services')).toBeInTheDocument()
    expect(screen.getByText('20 running')).toBeInTheDocument()
    expect(screen.getByText('11 healthy')).toBeInTheDocument()
    expect(screen.getByText('15 stopped')).toBeInTheDocument()
    expect(screen.queryByText(/unhealthy/)).not.toBeInTheDocument()
  })
})
