import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NoteEditorHeader } from '../../packages/notes-ui/src/NoteEditorHeader'

function renderHeader(confirmDelete: boolean) {
  return render(
    <NoteEditorHeader
      title="ut-test"
      pinned={false}
      mode="edit"
      saveState="idle"
      formatState="idle"
      canFormat={false}
      contentLength={0}
      confirmDelete={confirmDelete}
      onTitleChange={vi.fn()}
      onStartFormat={vi.fn()}
      onToggleHistory={vi.fn()}
      onTogglePin={vi.fn()}
      onSetMode={vi.fn()}
      onDelete={vi.fn()}
    />,
  )
}

describe('note delete button', () => {
  it('is labelled, and says what the second click does', () => {
    const { unmount } = renderHeader(false)
    expect(
      screen.getByRole('button', { name: 'Delete note' }),
    ).toBeInTheDocument()
    unmount()

    renderHeader(true)
    const confirm = screen.getByRole('button', {
      name: 'Confirm: delete this note',
    })
    expect(confirm).toHaveTextContent('Delete?')
  })
})
