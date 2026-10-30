import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Note } from '../../packages/notes-ui/src/types'
import { useNoteEditorState } from '../../packages/notes-ui/src/useNoteEditorState'

const mutate = vi.fn()
const create = vi.fn()
const remove = vi.fn()
vi.mock('../../packages/notes-ui/src/useNotes', () => ({
  useCreateNote: () => ({ mutateAsync: create }),
  useUpdateNote: () => ({ mutate }),
  useDeleteNote: () => ({ mutate: remove }),
}))

// Each create call returns a promise the test settles.
function deferCreates() {
  const settle: ((note: Note) => Promise<void>)[] = []
  create.mockImplementation(
    () =>
      new Promise<Note>((resolve) => {
        settle.push(async (n) => {
          resolve(n)
          await Promise.resolve()
          await Promise.resolve()
        })
      }),
  )
  return settle
}

const note = {
  id: 'n1',
  title: '',
  content: '',
  tags: [],
  pinned: false,
} as unknown as Note

describe('note editor autosave', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    create.mockReturnValue(new Promise(() => {}))
  })
  afterEach(() => {
    vi.useRealTimers()
    mutate.mockReset()
    create.mockReset()
    remove.mockReset()
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

  it('creates a new note only on its first edit, then updates it by id', async () => {
    const settle = deferCreates()
    const draft = {
      ...note,
      id: '',
      type: 'note',
      project_scope: 'summitflow',
    } as Note
    const onCreated = vi.fn()
    const { result } = renderHook(() =>
      useNoteEditorState({ note: draft, onDeleted: vi.fn(), onCreated }),
    )
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(create).not.toHaveBeenCalled()

    act(() => result.current.handleTitleChange('ut-test'))
    act(() => result.current.handleContentChange('body'))
    act(() => {
      vi.advanceTimersByTime(500)
    })
    expect(create).toHaveBeenCalledTimes(1)
    expect(create.mock.calls[0][0]).toEqual({
      title: 'ut-test',
      content: 'body',
      type: 'note',
      project_scope: 'summitflow',
    })
    const created = { ...draft, id: 'n2', title: 'ut-test', content: 'body' }
    await act(() => settle[0](created))
    expect(onCreated).toHaveBeenCalledWith(created)

    act(() => result.current.handleContentChange('body more'))
    act(() => {
      vi.advanceTimersByTime(500)
    })
    expect(create).toHaveBeenCalledTimes(1)
    expect(mutate.mock.calls[0][0]).toEqual({
      noteId: 'n2',
      data: { content: 'body more' },
    })
  })

  it('closes an untouched new note without saving anything', () => {
    const draft = { ...note, id: '' } as Note
    const onDeleted = vi.fn()
    const { result } = renderHook(() =>
      useNoteEditorState({ note: draft, onDeleted }),
    )

    act(() => result.current.handleDelete())

    expect(onDeleted).toHaveBeenCalled()
    expect(create).not.toHaveBeenCalled()
  })

  it('keeps a create that finishes after a switch off the note opened since', async () => {
    const settle = deferCreates()
    const onCreated = vi.fn()
    const first = { ...note, id: '' } as Note
    const { result, rerender } = renderHook(
      ({ current }) =>
        useNoteEditorState({ note: current, onDeleted: vi.fn(), onCreated }),
      { initialProps: { current: first } },
    )
    act(() => result.current.handleContentChange('first'))
    act(() => {
      vi.advanceTimersByTime(500)
    })
    expect(create).toHaveBeenCalledTimes(1)

    rerender({ current: { ...note, id: 'other' } as Note })
    rerender({ current: { ...note, id: '' } as Note })
    act(() => result.current.handleContentChange('second'))
    act(() => {
      vi.advanceTimersByTime(500)
    })
    expect(create).toHaveBeenCalledTimes(2)
    expect(create.mock.calls[1][0]).toMatchObject({ content: 'second' })

    await act(() => settle[0]({ ...first, id: 'n-first', content: 'first' }))
    expect(onCreated).not.toHaveBeenCalled()
    expect(mutate).not.toHaveBeenCalled()
  })

  it('asks before discarding a new note with unsaved text', () => {
    const onDeleted = vi.fn()
    const draft = { ...note, id: '' } as Note
    const { result } = renderHook(() =>
      useNoteEditorState({ note: draft, onDeleted }),
    )
    act(() => result.current.handleContentChange('half a thought'))

    act(() => result.current.handleDelete())
    expect(onDeleted).not.toHaveBeenCalled()
    expect(result.current.confirmDelete).toBe(true)

    act(() => result.current.handleDelete())
    expect(onDeleted).toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(create).not.toHaveBeenCalled()
  })

  it('clears the editor when New is clicked on an open draft', () => {
    const { result, rerender } = renderHook(
      ({ current }) =>
        useNoteEditorState({ note: current, onDeleted: vi.fn() }),
      { initialProps: { current: { ...note, id: '' } as Note } },
    )
    act(() => result.current.handleTitleChange('draft one'))

    rerender({ current: { ...note, id: '' } as Note })

    expect(result.current.title).toBe('')
  })
})
