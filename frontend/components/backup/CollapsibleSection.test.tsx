import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CollapsibleSection } from './CollapsibleSection'

describe('CollapsibleSection', () => {
  it('renders collapsed by default with the summary line visible', () => {
    render(
      <CollapsibleSection title="Overview" summary="2 healthy, 1 failing">
        <div>Expanded content</div>
      </CollapsibleSection>,
    )

    const toggle = screen.getByRole('button', { name: /overview/i })

    expect(screen.getByText('Overview')).toBeInTheDocument()
    expect(screen.getByText('2 healthy, 1 failing')).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('shows content after toggling open', () => {
    render(
      <CollapsibleSection title="Overview" summary="2 healthy, 1 failing">
        <div>Expanded content</div>
      </CollapsibleSection>,
    )

    fireEvent.click(screen.getByRole('button', { name: /overview/i }))

    expect(screen.getByText('Expanded content')).toBeInTheDocument()
  })
})
