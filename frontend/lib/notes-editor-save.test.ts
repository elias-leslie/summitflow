import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Note } from '../../packages/notes-ui/src/types'
import { useNoteEditorState } from '../../packages/notes-ui/src/useNoteEditorState'

const mutate = vi.fn()
vi.mock('../../packages/notes-ui/src/useNotes', () => ({
  useUpdateNote: () => ({ mutate }),
  useDeleteNote: () => ({ mutate: vi.fn() }),
}))

const note = {
  id: 'n1',
  title: '',
  content: '',
  tags: [],
  pinned: false,
} as unknown as Note

describe('note editor autosave', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    mutate.mockReset()
  })

  it('saves a title typed just before the body together with the body', () => {
    const { result } = renderHook(() =>
      useNoteEditorState({ note, onDeleted: vi.fn() }),
    )

    act(() => result.current.handleTitleChange('Groceries'))
    act(() => result.current.handleContentChange('milk'))
    act(() => {
      vi.advanceTimersByTime(500)
    })

    expect(mutate).toHaveBeenCalledTimes(1)
    expect(mutate.mock.calls[0][0]).toEqual({
      noteId: 'n1',
      data: { title: 'Groceries', content: 'milk' },
    })
  })
})
