import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StarRating } from './StarRating'

describe('StarRating', () => {
  it('says there are no ratings instead of showing a 0.0 average', () => {
    render(
      <StarRating average={0} count={0} userRating={0} onRate={() => {}} />,
    )

    expect(screen.getByText('No ratings yet')).toBeInTheDocument()
    expect(screen.queryByText(/0\.0/)).not.toBeInTheDocument()
  })

  it('shows the average and count once rated', () => {
    render(
      <StarRating average={4.5} count={2} userRating={0} onRate={() => {}} />,
    )

    expect(screen.getByText('4.5 · 2 ratings')).toBeInTheDocument()
  })
})
