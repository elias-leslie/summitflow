import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NotesButton } from '../../packages/notes-ui/src/NotesButton'

vi.mock('../../packages/notes-ui/src/NotesProvider', () => ({
  useNotesContext: () => ({ api: { list: () => Promise.resolve([]) } }),
}))
vi.mock('../../packages/notes-ui/src/NotesPanel', () => ({
  NotesPanel: () => <div data-testid="notes-panel" />,
}))

const originalWidth = window.innerWidth

describe('NotesButton panel', () => {
  afterEach(() => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: originalWidth,
    })
    vi.restoreAllMocks()
  })

  it('fits a phone screen when it opens leftward from a header button on the right', () => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 390,
    })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 265,
      right: 305,
      top: 10,
      bottom: 50,
      width: 40,
      height: 40,
      x: 265,
      y: 10,
      toJSON: () => ({}),
    })
    render(<NotesButton />)

    fireEvent.click(screen.getByRole('button', { name: 'Notes' }))

    const panel = screen.getByTestId('notes-panel').parentElement as HTMLElement
    expect(panel.style.right).toBe('85px')
    expect(panel.style.width).toBe('297px')
  })
})
