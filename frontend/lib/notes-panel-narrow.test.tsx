import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NotesPanel } from '../../packages/notes-ui/src/NotesPanel'

vi.mock('../../packages/notes-ui/src/NotesProvider', () => ({
  useNotesContext: () => ({
    projectScope: 'summitflow',
    scopeOptions: [],
    getScopeLabel: (scope: string) => scope,
  }),
}))
vi.mock('../../packages/notes-ui/src/NotesList', () => ({
  NotesList: ({ onSelect }: { onSelect: (note: { id: string }) => void }) => (
    <button type="button" onClick={() => onSelect({ id: 'n1' })}>
      Groceries
    </button>
  ),
}))
vi.mock('../../packages/notes-ui/src/NoteEditor', () => ({
  NoteEditor: () => <div data-testid="editor" />,
}))

function panelWidth(width: number) {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width,
    height: 600,
    left: 0,
    right: width,
    top: 0,
    bottom: 600,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
}

describe('NotesPanel width', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows the list or the open note, not both, in a phone-width panel', () => {
    panelWidth(297)
    render(<NotesPanel />)
    expect(screen.queryByText(/Select or create/)).toBeNull()

    fireEvent.click(screen.getByText('Groceries'))
    expect(screen.getByTestId('editor')).toBeTruthy()
    expect(screen.queryByText('Groceries')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'All notes' }))
    expect(screen.getByText('Groceries')).toBeTruthy()
    expect(screen.queryByTestId('editor')).toBeNull()
  })

  it('keeps the list beside the editor in a wide panel', () => {
    panelWidth(700)
    render(<NotesPanel />)
    fireEvent.click(screen.getByText('Groceries'))
    expect(screen.getByTestId('editor')).toBeTruthy()
    expect(screen.getByText('Groceries')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'All notes' })).toBeNull()
  })
})
