'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  ArrowDown,
  ArrowUp,
  Code2,
  Eye,
  Grip,
  MessageSquarePlus,
  MousePointer2,
  Save,
  Send,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  type CreateMockupRequest,
  createMockup,
  type Mockup,
} from '@/lib/api/mockups'
import {
  extractMockupAnnotations,
  summarizeMockupForWorkContext,
} from '@/lib/mockup-html'
import { getErrorMessage } from '@/lib/utils'

type EditorMode = 'inspect' | 'text' | 'move' | 'note'
type CompareMode = 'current' | 'split' | 'original'

interface SelectedElementState {
  id: string
  tag: string
  label: string
  text: string
  color: string
  backgroundColor: string
  margin: string
  padding: string
  borderRadius: string
}

interface MockupSurfaceEditorProps {
  mockup: Mockup
  projectId: string
  onSaved?: (mockup: Mockup) => void
  onSendToJenny?: (payload: {
    sourceMockup: Mockup
    savedMockup?: Mockup
    content: string
    summary: string
  }) => void
}

const EDITOR_STYLE_ID = 'sf-mock-editor-style'
const SELECTED_CLASS = 'sf-editor-selected'
const HOVER_CLASS = 'sf-editor-hover'

const editorCss = `
  .${HOVER_CLASS} {
    outline: 1px dashed rgba(0, 245, 255, 0.75) !important;
    outline-offset: 2px !important;
    cursor: pointer !important;
  }
  .${SELECTED_CLASS} {
    outline: 2px solid rgba(0, 245, 255, 0.95) !important;
    outline-offset: 3px !important;
    box-shadow: 0 0 0 5px rgba(0, 245, 255, 0.12) !important;
  }
  .sf-mock-note {
    position: absolute;
    z-index: 2147483000;
    min-width: 180px;
    max-width: 260px;
    border: 1px solid rgba(0, 245, 255, 0.45);
    border-radius: 10px;
    background: rgba(7, 4, 13, 0.96);
    color: #dffcff;
    padding: 10px 12px;
    font: 13px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.4), 0 0 22px rgba(0, 245, 255, 0.14);
  }
  .sf-mock-note::before {
    content: "";
    position: absolute;
    left: -46px;
    top: 18px;
    width: 46px;
    height: 1px;
    background: rgba(0, 245, 255, 0.75);
    transform: rotate(-12deg);
    transform-origin: right center;
  }
  .sf-mock-note::after {
    content: "";
    position: absolute;
    left: -50px;
    top: 21px;
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: #00f5ff;
    box-shadow: 0 0 12px rgba(0, 245, 255, 0.75);
  }
`

function labelForElement(element: HTMLElement): string {
  const bits = [element.tagName.toLowerCase()]
  if (element.id) bits.push(`#${element.id}`)
  if (element.className && typeof element.className === 'string') {
    bits.push(
      `.${element.className
        .split(/\s+/)
        .filter((item) => item && !item.startsWith('sf-editor-'))
        .slice(0, 2)
        .join('.')}`,
    )
  }
  return bits.join('')
}

function getEditableElements(doc: Document): HTMLElement[] {
  return Array.from(doc.body?.querySelectorAll<HTMLElement>('*') ?? []).filter(
    (element) =>
      element.tagName !== 'SCRIPT' &&
      element.tagName !== 'STYLE' &&
      !element.closest(`[data-sf-editor-ui="true"]`),
  )
}

function selectedStateFromElement(element: HTMLElement): SelectedElementState {
  return {
    id: element.dataset.sfEditorId ?? '',
    tag: element.tagName.toLowerCase(),
    label: labelForElement(element),
    text: element.textContent?.trim().slice(0, 2000) ?? '',
    color: element.style.color,
    backgroundColor: element.style.backgroundColor,
    margin: element.style.margin,
    padding: element.style.padding,
    borderRadius: element.style.borderRadius,
  }
}

function stripEditorState(doc: Document): string {
  doc.getElementById(EDITOR_STYLE_ID)?.remove()
  doc
    .querySelectorAll(`.${SELECTED_CLASS}, .${HOVER_CLASS}`)
    .forEach((element) => {
      element.classList.remove(SELECTED_CLASS, HOVER_CLASS)
      element.removeAttribute('contenteditable')
    })
  doc.querySelectorAll('[data-sf-editor-id]').forEach((element) => {
    element.removeAttribute('data-sf-editor-id')
  })
  return `<!doctype html>\n${doc.documentElement.outerHTML}`
}

function buildVersionPayload(
  source: Mockup,
  content: string,
  summary: string,
): CreateMockupRequest {
  return {
    name: `${source.name} edited`,
    description: `Surface-edited version of ${source.name}`,
    mockup_type: source.mockup_type,
    content,
    task_id: source.task_id ?? undefined,
    page_path: source.page_path ?? undefined,
    parent_mockup_id: source.id,
    generator: 'surface-editor',
    generation_prompt: summary,
  }
}

export function MockupSurfaceEditor({
  mockup,
  projectId,
  onSaved,
  onSendToJenny,
}: MockupSurfaceEditorProps) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null)
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<EditorMode>('inspect')
  const [compareMode, setCompareMode] = useState<CompareMode>('current')
  const [selected, setSelected] = useState<SelectedElementState | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [noteText, setNoteText] = useState('')
  const [dirty, setDirty] = useState(false)
  const [lastSavedMockup, setLastSavedMockup] = useState<Mockup | null>(null)
  const [draftKey, setDraftKey] = useState(0)
  const [frameRevision, setFrameRevision] = useState(0)

  const content = mockup.content ?? ''
  const notes = useMemo(() => extractMockupAnnotations(content), [content])

  const getDoc = useCallback(
    () => iframeRef.current?.contentDocument ?? null,
    [],
  )

  const getSelectedElement = useCallback((): HTMLElement | null => {
    const doc = getDoc()
    if (!doc || !selectedId) return null
    return doc.querySelector<HTMLElement>(
      `[data-sf-editor-id="${CSS.escape(selectedId)}"]`,
    )
  }, [getDoc, selectedId])

  const refreshSelected = useCallback(
    (id: string | null = selectedId) => {
      const doc = getDoc()
      if (!doc || !id) {
        setSelected(null)
        return
      }
      const element = doc.querySelector<HTMLElement>(
        `[data-sf-editor-id="${CSS.escape(id)}"]`,
      )
      setSelected(element ? selectedStateFromElement(element) : null)
    },
    [getDoc, selectedId],
  )

  const selectElement = useCallback(
    (element: HTMLElement | null) => {
      const doc = getDoc()
      if (!doc) return
      doc
        .querySelectorAll(`.${SELECTED_CLASS}`)
        .forEach((item) => item.classList.remove(SELECTED_CLASS))

      if (!element) {
        setSelectedId(null)
        setSelected(null)
        return
      }

      const id = element.dataset.sfEditorId
      if (!id) return
      element.classList.add(SELECTED_CLASS)
      setSelectedId(id)
      setSelected(selectedStateFromElement(element))
    },
    [getDoc],
  )

  const prepareDocument = useCallback(() => {
    const doc = getDoc()
    if (!doc?.body) return

    doc.getElementById(EDITOR_STYLE_ID)?.remove()
    const style = doc.createElement('style')
    style.id = EDITOR_STYLE_ID
    style.textContent = editorCss
    doc.head.appendChild(style)

    getEditableElements(doc).forEach((element, index) => {
      element.dataset.sfEditorId = `el-${index}`
      element.classList.remove(SELECTED_CLASS, HOVER_CLASS)
    })
    setSelected(null)
    setSelectedId(null)
    setFrameRevision((current) => current + 1)
  }, [getDoc])

  useEffect(() => {
    setDraftKey((current) => current + 1)
    setDirty(false)
    setLastSavedMockup(null)
  }, [mockup.mockup_id])

  useEffect(() => {
    const doc = getDoc()
    if (!doc?.body) return

    let drag: {
      element: HTMLElement
      startX: number
      startY: number
      baseX: number
      baseY: number
    } | null = null

    const onPointerOver = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null
      if (!target || target === doc.body || target === doc.documentElement) {
        return
      }
      target.classList.add(HOVER_CLASS)
    }

    const onPointerOut = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null
      target?.classList.remove(HOVER_CLASS)
    }

    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (!target || target === doc.body || target === doc.documentElement) {
        return
      }
      event.preventDefault()
      event.stopPropagation()
      selectElement(target)
      if (mode === 'note') {
        setNoteText(target.dataset.sfMockNoteText ?? '')
      }
    }

    const onPointerDown = (event: PointerEvent) => {
      if (mode !== 'move') return
      const target = event.target as HTMLElement | null
      if (!target || target === doc.body || target === doc.documentElement) {
        return
      }
      event.preventDefault()
      event.stopPropagation()
      selectElement(target)
      const baseX = Number.parseFloat(target.dataset.sfOffsetX ?? '0') || 0
      const baseY = Number.parseFloat(target.dataset.sfOffsetY ?? '0') || 0
      target.style.position ||= 'relative'
      target.style.zIndex ||= '2'
      drag = {
        element: target,
        startX: event.clientX,
        startY: event.clientY,
        baseX,
        baseY,
      }
    }

    const onPointerMove = (event: PointerEvent) => {
      if (!drag) return
      const x = Math.round(drag.baseX + event.clientX - drag.startX)
      const y = Math.round(drag.baseY + event.clientY - drag.startY)
      drag.element.dataset.sfOffsetX = String(x)
      drag.element.dataset.sfOffsetY = String(y)
      drag.element.style.transform = `translate(${x}px, ${y}px)`
      setDirty(true)
    }

    const onPointerUp = () => {
      drag = null
      refreshSelected()
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Delete' && event.key !== 'Backspace') return
      const element = getSelectedElement()
      if (!element) return
      event.preventDefault()
      element.remove()
      selectElement(null)
      setDirty(true)
    }

    doc.addEventListener('pointerover', onPointerOver)
    doc.addEventListener('pointerout', onPointerOut)
    doc.addEventListener('click', onClick, true)
    doc.addEventListener('pointerdown', onPointerDown, true)
    doc.addEventListener('pointermove', onPointerMove, true)
    doc.addEventListener('pointerup', onPointerUp, true)
    doc.addEventListener('keydown', onKeyDown)

    return () => {
      doc.removeEventListener('pointerover', onPointerOver)
      doc.removeEventListener('pointerout', onPointerOut)
      doc.removeEventListener('click', onClick, true)
      doc.removeEventListener('pointerdown', onPointerDown, true)
      doc.removeEventListener('pointermove', onPointerMove, true)
      doc.removeEventListener('pointerup', onPointerUp, true)
      doc.removeEventListener('keydown', onKeyDown)
    }
  }, [
    getDoc,
    getSelectedElement,
    mode,
    refreshSelected,
    selectElement,
    selectedId,
    frameRevision,
  ])

  const serializeDraft = useCallback(() => {
    const doc = getDoc()
    if (!doc?.documentElement) return content
    const clone = doc.cloneNode(true) as Document
    return stripEditorState(clone)
  }, [content, getDoc])

  const buildSummary = useCallback(
    (draftContent: string) => {
      const draftNotes = extractMockupAnnotations(draftContent)
      const lines = [
        `Surface-edited mockup ${mockup.mockup_id} v${mockup.version}.`,
      ]
      if (dirty) lines.push('User made direct surface edits.')
      if (draftNotes.length) {
        lines.push('Anchored notes:')
        draftNotes.forEach((note) => lines.push(`- ${note}`))
      }
      return lines.join('\n')
    },
    [dirty, mockup.mockup_id, mockup.version],
  )

  const saveMutation = useMutation({
    mutationFn: async () => {
      const draftContent = serializeDraft()
      const summary = buildSummary(draftContent)
      return createMockup(
        projectId,
        buildVersionPayload(mockup, draftContent, summary),
      )
    },
    onSuccess: (saved) => {
      setDirty(false)
      setLastSavedMockup(saved)
      queryClient.invalidateQueries({ queryKey: ['mockups', projectId] })
      queryClient.invalidateQueries({ queryKey: ['mockup-stats', projectId] })
      queryClient.invalidateQueries({
        queryKey: ['mockup-history', projectId, mockup.mockup_id],
      })
      toast.success('Mockup version saved')
      onSaved?.(saved)
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to save mockup version'))
    },
  })

  const updateSelectedText = (value: string) => {
    const element = getSelectedElement()
    if (!element) return
    element.textContent = value
    element.dataset.sfMockNoteText = element.classList.contains('sf-mock-note')
      ? value
      : (element.dataset.sfMockNoteText ?? '')
    setSelected((current) => (current ? { ...current, text: value } : current))
    setDirty(true)
  }

  const updateStyle = (
    key: keyof Pick<
      SelectedElementState,
      'color' | 'backgroundColor' | 'margin' | 'padding' | 'borderRadius'
    >,
    value: string,
  ) => {
    const element = getSelectedElement()
    if (!element) return
    element.style[key] = value
    setSelected((current) => (current ? { ...current, [key]: value } : current))
    setDirty(true)
  }

  const removeSelected = () => {
    const element = getSelectedElement()
    if (!element) return
    element.remove()
    selectElement(null)
    setDirty(true)
  }

  const moveSelectedSibling = (direction: 'before' | 'after') => {
    const element = getSelectedElement()
    if (!element?.parentElement) return
    const sibling =
      direction === 'before'
        ? element.previousElementSibling
        : element.nextElementSibling
    if (!sibling) return
    if (direction === 'before') {
      element.parentElement.insertBefore(element, sibling)
    } else {
      element.parentElement.insertBefore(sibling, element)
    }
    setDirty(true)
  }

  const addNote = () => {
    const doc = getDoc()
    const element = getSelectedElement()
    const note = noteText.trim()
    if (!doc?.body || !element || !note) return
    const rect = element.getBoundingClientRect()
    const bubble = doc.createElement('div')
    bubble.className = 'sf-mock-note'
    bubble.dataset.sfMockNoteText = note
    bubble.textContent = note
    bubble.style.left = `${Math.max(12, rect.right + doc.defaultView!.scrollX + 52)}px`
    bubble.style.top = `${Math.max(12, rect.top + doc.defaultView!.scrollY)}px`
    doc.body.appendChild(bubble)
    bubble.dataset.sfEditorId = `note-${Date.now()}`
    selectElement(bubble)
    setDirty(true)
  }

  const sendToJenny = () => {
    const draftContent = serializeDraft()
    const savedMockup = lastSavedMockup ?? undefined
    const summary = [
      buildSummary(draftContent),
      '',
      `Current artifact summary: ${summarizeMockupForWorkContext(savedMockup ?? mockup)}`,
    ].join('\n')
    onSendToJenny?.({
      sourceMockup: mockup,
      savedMockup,
      content: draftContent,
      summary,
    })
  }

  const toolButtonClass = (item: EditorMode) =>
    clsx(
      'inline-flex h-8 items-center gap-1.5 rounded border px-2 text-xs transition-colors',
      mode === item
        ? 'border-phosphor-500/50 bg-phosphor-500/12 text-phosphor-200'
        : 'border-slate-700 bg-slate-950/70 text-slate-400 hover:border-slate-600 hover:text-slate-200',
    )

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-10 shrink-0 items-center gap-1 overflow-x-auto border-b border-slate-800 bg-slate-900/85 px-2">
            <button
              type="button"
              onClick={() => setMode('inspect')}
              className={toolButtonClass('inspect')}
            >
              <MousePointer2 className="h-3.5 w-3.5" />
              Select
            </button>
            <button
              type="button"
              onClick={() => setMode('text')}
              className={toolButtonClass('text')}
            >
              <Code2 className="h-3.5 w-3.5" />
              Text
            </button>
            <button
              type="button"
              onClick={() => setMode('move')}
              className={toolButtonClass('move')}
            >
              <Grip className="h-3.5 w-3.5" />
              Move
            </button>
            <button
              type="button"
              onClick={() => setMode('note')}
              className={toolButtonClass('note')}
            >
              <MessageSquarePlus className="h-3.5 w-3.5" />
              Note
            </button>

            <div className="mx-1 h-5 w-px shrink-0 bg-slate-800" />

            {(['current', 'split', 'original'] as CompareMode[]).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setCompareMode(item)}
                className={clsx(
                  'h-8 rounded border px-2 text-xs capitalize transition-colors',
                  compareMode === item
                    ? 'border-slate-500 bg-slate-800 text-slate-100'
                    : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300',
                )}
              >
                {item}
              </button>
            ))}

            <div className="flex-1" />
            {dirty ? (
              <span className="rounded border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-xs text-amber-300">
                Unsaved
              </span>
            ) : null}
            {onSendToJenny ? (
              <button
                type="button"
                onClick={sendToJenny}
                className="inline-flex h-8 items-center gap-1.5 rounded border border-phosphor-500/30 bg-phosphor-500/10 px-2 text-xs text-phosphor-200 hover:bg-phosphor-500/15"
              >
                <Send className="h-3.5 w-3.5" />
                Jenny
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="inline-flex h-8 items-center gap-1.5 rounded border border-outrun-500 bg-outrun-600 px-2 text-xs text-slate-50 hover:bg-outrun-500 disabled:opacity-50"
            >
              <Save className="h-3.5 w-3.5" />
              {saveMutation.isPending ? 'Saving' : 'Save version'}
            </button>
          </div>

          <div
            className={clsx(
              'grid min-h-0 flex-1 bg-[#07040d]',
              compareMode === 'split' && 'lg:grid-cols-2',
            )}
          >
            {compareMode !== 'current' ? (
              <div className="relative min-h-0 border-r border-slate-800">
                <div className="absolute left-2 top-2 z-10 rounded border border-slate-700 bg-slate-950/85 px-2 py-1 text-xs text-slate-300">
                  Original
                </div>
                <iframe
                  srcDoc={content}
                  title={`${mockup.name} original`}
                  sandbox="allow-same-origin"
                  className="h-full w-full border-0 bg-white"
                />
              </div>
            ) : null}
            {compareMode !== 'original' ? (
              <div className="relative min-h-0">
                <div className="absolute left-2 top-2 z-10 rounded border border-phosphor-500/30 bg-slate-950/85 px-2 py-1 text-xs text-phosphor-200">
                  Editable surface
                </div>
                <iframe
                  key={`${mockup.mockup_id}-${draftKey}`}
                  ref={iframeRef}
                  srcDoc={content}
                  title={`${mockup.name} editable`}
                  sandbox="allow-same-origin"
                  onLoad={prepareDocument}
                  className="h-full w-full border-0 bg-white"
                />
              </div>
            ) : null}
          </div>
        </div>

        <aside className="hidden w-80 shrink-0 border-l border-slate-800 bg-slate-900/70 p-3 lg:block">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-200">
            <Eye className="h-4 w-4 text-phosphor-300" />
            Surface Inspector
          </div>

          {selected ? (
            <div className="space-y-3">
              <div className="rounded border border-slate-800 bg-slate-950/70 p-2">
                <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
                  Selected
                </div>
                <div className="mt-1 truncate font-mono text-xs text-phosphor-200">
                  {selected.label}
                </div>
              </div>

              <label className="grid gap-1 text-xs text-slate-400">
                Text
                <textarea
                  value={selected.text}
                  onChange={(event) => updateSelectedText(event.target.value)}
                  rows={5}
                  className="rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 focus:border-phosphor-500/60 focus:outline-none"
                />
              </label>

              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => moveSelectedSibling('before')}
                  className="btn-secondary inline-flex items-center justify-center gap-1 text-xs"
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                  Reorder
                </button>
                <button
                  type="button"
                  onClick={() => moveSelectedSibling('after')}
                  className="btn-secondary inline-flex items-center justify-center gap-1 text-xs"
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                  Reorder
                </button>
              </div>

              <div className="grid gap-2">
                {(
                  [
                    ['color', 'Color'],
                    ['backgroundColor', 'Background'],
                    ['margin', 'Margin'],
                    ['padding', 'Padding'],
                    ['borderRadius', 'Radius'],
                  ] as const
                ).map(([key, label]) => (
                  <label
                    key={key}
                    className="grid gap-1 text-xs text-slate-400"
                  >
                    {label}
                    <input
                      value={selected[key]}
                      onChange={(event) => updateStyle(key, event.target.value)}
                      placeholder={
                        key === 'color'
                          ? '#e2e8f0'
                          : key === 'padding'
                            ? '12px'
                            : ''
                      }
                      className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-phosphor-500/60 focus:outline-none"
                    />
                  </label>
                ))}
              </div>

              <label className="grid gap-1 text-xs text-slate-400">
                Anchored note
                <textarea
                  value={noteText}
                  onChange={(event) => setNoteText(event.target.value)}
                  rows={3}
                  placeholder="What should Jenny change here?"
                  className="rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 focus:border-phosphor-500/60 focus:outline-none"
                />
              </label>
              <button
                type="button"
                onClick={addNote}
                disabled={!noteText.trim()}
                className="w-full btn-secondary inline-flex items-center justify-center gap-1 text-xs disabled:opacity-50"
              >
                <MessageSquarePlus className="h-3.5 w-3.5" />
                Add note bubble
              </button>

              <button
                type="button"
                onClick={removeSelected}
                className="w-full rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300 transition-colors hover:bg-rose-500/15"
              >
                <Trash2 className="mr-1 inline h-3.5 w-3.5" />
                Delete selected
              </button>
            </div>
          ) : (
            <div className="rounded border border-dashed border-slate-800 bg-slate-950/50 p-4 text-sm text-slate-500">
              Select an element on the mock surface.
            </div>
          )}

          {notes.length ? (
            <div className="mt-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-[0.14em] text-slate-500">
                Existing Notes
              </div>
              <div className="space-y-2">
                {notes.map((note, index) => (
                  <div
                    key={`${note}-${index}`}
                    className="rounded border border-phosphor-500/20 bg-phosphor-500/8 p-2 text-xs text-phosphor-100"
                  >
                    {note}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  )
}
