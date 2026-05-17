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
  buildMockupElementPath,
  describeMockupElement,
  extractMockupAnnotations,
  extractStructuredMockupAnnotations,
  type MockupAnnotation,
  summarizeMockupForWorkContext,
} from '@/lib/mockup-html'
import { getErrorMessage } from '@/lib/utils'

type EditorMode = 'inspect' | 'text' | 'move' | 'note'
type CompareMode = 'current' | 'split' | 'original'
type EditableStyleKey = keyof Pick<
  SelectedElementState,
  'color' | 'backgroundColor' | 'margin' | 'padding' | 'borderRadius'
>

interface SelectedElementState {
  id: string
  path: string
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
    summary: string
  }) => void
}

interface ToolbarProps {
  mode: EditorMode
  compareMode: CompareMode
  dirty: boolean
  canSendToJenny: boolean
  isSaving: boolean
  onModeChange: (mode: EditorMode) => void
  onCompareModeChange: (mode: CompareMode) => void
  onSendToJenny: () => void
  onSave: () => void
}

interface SurfaceFrameProps {
  compareMode: CompareMode
  content: string
  mockup: Mockup
  draftKey: number
  iframeRef: React.RefObject<HTMLIFrameElement | null>
  onLoad: () => void
}

interface InspectorProps {
  selected: SelectedElementState | null
  selectedCount: number
  noteText: string
  notes: string[]
  onTextChange: (value: string) => void
  onMoveSibling: (direction: 'before' | 'after') => void
  onStyleChange: (key: EditableStyleKey, value: string) => void
  onNoteTextChange: (value: string) => void
  onAddNote: () => void
  onRemoveSelected: () => void
}

const EDITOR_STYLE_ID = 'sf-mock-editor-style'
const SELECTED_CLASS = 'sf-editor-selected'
const HOVER_CLASS = 'sf-editor-hover'
const COMPARE_MODES: CompareMode[] = ['current', 'split', 'original']
const STYLE_FIELDS: Array<{
  key: EditableStyleKey
  label: string
  placeholder: string
}> = [
  { key: 'color', label: 'Color', placeholder: '#e2e8f0' },
  { key: 'backgroundColor', label: 'Background', placeholder: '' },
  { key: 'margin', label: 'Margin', placeholder: '' },
  { key: 'padding', label: 'Padding', placeholder: '12px' },
  { key: 'borderRadius', label: 'Radius', placeholder: '' },
]
const MODE_BUTTONS: Array<{
  value: EditorMode
  label: string
  Icon: typeof MousePointer2
}> = [
  { value: 'inspect', label: 'Select', Icon: MousePointer2 },
  { value: 'text', label: 'Text', Icon: Code2 },
  { value: 'move', label: 'Move', Icon: Grip },
  { value: 'note', label: 'Note', Icon: MessageSquarePlus },
]

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
  return describeMockupElement(element)
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
    path: buildMockupElementPath(element),
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
  metadata: Record<string, unknown>,
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
    metadata,
  }
}

function getElementByEditorId(doc: Document | null, id: string | null) {
  if (!doc || !id) return null
  return doc.querySelector<HTMLElement>(
    `[data-sf-editor-id="${CSS.escape(id)}"]`,
  )
}

function getElementsByEditorIds(doc: Document | null, ids: string[]) {
  if (!doc || !ids.length) return []
  return ids
    .map((id) => getElementByEditorId(doc, id))
    .filter((element): element is HTMLElement => Boolean(element))
}

function applySelection(doc: Document, ids: string[]) {
  doc
    .querySelectorAll(`.${SELECTED_CLASS}`)
    .forEach((item) => item.classList.remove(SELECTED_CLASS))
  ids.forEach((id) => {
    getElementByEditorId(doc, id)?.classList.add(SELECTED_CLASS)
  })
}

function clearSelectionState(doc: Document) {
  applySelection(doc, [])
}

function clearDragState() {
  dragRef = null
}

function toggleSelectedIds(
  currentIds: string[],
  id: string,
  additive: boolean,
) {
  if (!additive || !currentIds.length) return [id]
  return currentIds.includes(id)
    ? currentIds.filter((item) => item !== id)
    : [...currentIds, id]
}

function extractAnnotationsForDraft(
  annotations: MockupAnnotation[],
  draftContent: string,
  metadata: Mockup['metadata'],
) {
  return annotations.length
    ? annotations
    : extractStructuredMockupAnnotations(draftContent, metadata)
}

function buildEditorSummary(
  mockup: Mockup,
  annotations: MockupAnnotation[],
  dirty: boolean,
  draftContent: string,
) {
  const draftNotes = extractAnnotationsForDraft(
    annotations,
    draftContent,
    mockup.metadata,
  )
  const lines = [
    `Surface-edited mockup ${mockup.mockup_id} v${mockup.version}.`,
  ]
  if (dirty) lines.push('User made direct surface edits.')
  if (draftNotes.length) {
    lines.push('Anchored notes:')
    draftNotes.forEach((item) => {
      lines.push(
        `- ${item.element_label ?? item.element_path ?? 'surface'}: ${item.note}`,
      )
    })
  }
  return lines.join('\n')
}

function serializeDraftDocument(doc: Document | null, fallback: string) {
  if (!doc?.documentElement) return fallback
  const clone = doc.cloneNode(true) as Document
  return stripEditorState(clone)
}

function removeElements(elements: HTMLElement[]) {
  elements.forEach((element) => element.remove())
}

function buildEditorMetadata(
  mockup: Mockup,
  annotations: MockupAnnotation[],
  draftContent: string,
): Record<string, unknown> {
  return {
    ...(mockup.metadata ?? {}),
    annotations: extractAnnotationsForDraft(
      annotations,
      draftContent,
      mockup.metadata,
    ),
    edited_by: 'surface-editor',
    source_mockup_id: mockup.mockup_id,
    source_version: mockup.version,
    summary_version: 1,
    token_policy: {
      default_context: 'compact',
      full_html: 'on_request',
    },
  }
}

const TOOLBAR_BUTTON_BASE =
  'inline-flex h-8 items-center gap-1.5 rounded border px-2 text-xs transition-colors'
const TOOLBAR_BUTTON_ACTIVE =
  'border-phosphor-500/50 bg-phosphor-500/12 text-phosphor-200'
const TOOLBAR_BUTTON_IDLE =
  'border-slate-700 bg-slate-950/70 text-slate-400 hover:border-slate-600 hover:text-slate-200'
const COMPARE_BUTTON_BASE =
  'h-8 rounded border px-2 text-xs capitalize transition-colors'
const COMPARE_BUTTON_ACTIVE = 'border-slate-500 bg-slate-800 text-slate-100'
const COMPARE_BUTTON_IDLE =
  'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'

// --- Shared drag state for move mode ---
interface DragState {
  elements: Array<{ element: HTMLElement; baseX: number; baseY: number }>
  startX: number
  startY: number
}
let dragRef: DragState | null = null

function EditorToolbar({
  mode,
  compareMode,
  dirty,
  canSendToJenny,
  isSaving,
  onModeChange,
  onCompareModeChange,
  onSendToJenny,
  onSave,
}: ToolbarProps) {
  return (
    <div className="flex h-10 shrink-0 items-center gap-1 overflow-x-auto border-b border-slate-800 bg-slate-900/85 px-2">
      {MODE_BUTTONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          onClick={() => onModeChange(value)}
          className={clsx(
            TOOLBAR_BUTTON_BASE,
            mode === value ? TOOLBAR_BUTTON_ACTIVE : TOOLBAR_BUTTON_IDLE,
          )}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </button>
      ))}

      <div className="mx-1 h-5 w-px shrink-0 bg-slate-800" />

      {COMPARE_MODES.map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => onCompareModeChange(item)}
          className={clsx(
            COMPARE_BUTTON_BASE,
            compareMode === item ? COMPARE_BUTTON_ACTIVE : COMPARE_BUTTON_IDLE,
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
      {canSendToJenny ? (
        <button
          type="button"
          onClick={onSendToJenny}
          className="inline-flex h-8 items-center gap-1.5 rounded border border-phosphor-500/30 bg-phosphor-500/10 px-2 text-xs text-phosphor-200 hover:bg-phosphor-500/15"
        >
          <Send className="h-3.5 w-3.5" />
          Jenny
        </button>
      ) : null}
      <button
        type="button"
        onClick={onSave}
        disabled={isSaving}
        className="inline-flex h-8 items-center gap-1.5 rounded border border-outrun-500 bg-outrun-600 px-2 text-xs text-slate-50 hover:bg-outrun-500 disabled:opacity-50"
      >
        <Save className="h-3.5 w-3.5" />
        {isSaving ? 'Saving' : 'Save version'}
      </button>
    </div>
  )
}

function SurfaceFrames({
  compareMode,
  content,
  mockup,
  draftKey,
  iframeRef,
  onLoad,
}: SurfaceFrameProps) {
  return (
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
            onLoad={onLoad}
            className="h-full w-full border-0 bg-white"
          />
        </div>
      ) : null}
    </div>
  )
}

function SurfaceInspector({
  selected,
  selectedCount,
  noteText,
  notes,
  onTextChange,
  onMoveSibling,
  onStyleChange,
  onNoteTextChange,
  onAddNote,
  onRemoveSelected,
}: InspectorProps) {
  return (
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
              {selectedCount > 1 ? ` (${selectedCount})` : ''}
            </div>
            <div className="mt-1 truncate font-mono text-xs text-phosphor-200">
              {selected.label}
            </div>
            <div className="mt-1 line-clamp-2 font-mono text-[10px] text-slate-500">
              {selected.path}
            </div>
          </div>

          <label className="grid gap-1 text-xs text-slate-400">
            Text
            <textarea
              value={selected.text}
              onChange={(event) => onTextChange(event.target.value)}
              rows={5}
              className="rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 focus:border-phosphor-500/60 focus:outline-none"
            />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => onMoveSibling('before')}
              className="btn-secondary inline-flex items-center justify-center gap-1 text-xs"
            >
              <ArrowUp className="h-3.5 w-3.5" />
              Reorder
            </button>
            <button
              type="button"
              onClick={() => onMoveSibling('after')}
              className="btn-secondary inline-flex items-center justify-center gap-1 text-xs"
            >
              <ArrowDown className="h-3.5 w-3.5" />
              Reorder
            </button>
          </div>

          <div className="grid gap-2">
            {STYLE_FIELDS.map(({ key, label, placeholder }) => (
              <label key={key} className="grid gap-1 text-xs text-slate-400">
                {label}
                <input
                  value={selected[key]}
                  onChange={(event) => onStyleChange(key, event.target.value)}
                  placeholder={placeholder}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-phosphor-500/60 focus:outline-none"
                />
              </label>
            ))}
          </div>

          <label className="grid gap-1 text-xs text-slate-400">
            Anchored note
            <textarea
              value={noteText}
              onChange={(event) => onNoteTextChange(event.target.value)}
              rows={3}
              placeholder="What should Jenny change here?"
              className="rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 focus:border-phosphor-500/60 focus:outline-none"
            />
          </label>
          <button
            type="button"
            onClick={onAddNote}
            disabled={!noteText.trim()}
            className="w-full btn-secondary inline-flex items-center justify-center gap-1 text-xs disabled:opacity-50"
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
            Add note bubble
          </button>

          <button
            type="button"
            onClick={onRemoveSelected}
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
  )
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
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [noteText, setNoteText] = useState('')
  const [dirty, setDirty] = useState(false)
  const [lastSavedMockup, setLastSavedMockup] = useState<Mockup | null>(null)
  const [draftKey, setDraftKey] = useState(0)
  const [frameRevision, setFrameRevision] = useState(0)
  const [annotations, setAnnotations] = useState<MockupAnnotation[]>(() =>
    extractStructuredMockupAnnotations(mockup.content, mockup.metadata),
  )

  const content = mockup.content ?? ''
  const notes = useMemo(
    () =>
      annotations.length
        ? annotations.map((item) => item.note)
        : extractMockupAnnotations(content),
    [annotations, content],
  )

  const getDoc = useCallback(
    () => iframeRef.current?.contentDocument ?? null,
    [],
  )

  const getSelectedElement = useCallback(
    () => getElementByEditorId(getDoc(), selectedId),
    [getDoc, selectedId],
  )

  const getSelectedElements = useCallback(
    () => getElementsByEditorIds(getDoc(), selectedIds),
    [getDoc, selectedIds],
  )

  const refreshSelected = useCallback(
    (id: string | null = selectedId) => {
      const element = getElementByEditorId(getDoc(), id)
      setSelected(element ? selectedStateFromElement(element) : null)
    },
    [getDoc, selectedId],
  )

  const selectElement = useCallback(
    (element: HTMLElement | null, additive = false) => {
      const doc = getDoc()
      if (!doc) return

      if (!element) {
        setSelectedId(null)
        setSelectedIds([])
        setSelected(null)
        clearSelectionState(doc)
        return
      }

      const id = element.dataset.sfEditorId
      if (!id) return
      const nextIds = toggleSelectedIds(selectedIds, id, additive)
      applySelection(doc, nextIds)
      setSelectedId(id)
      setSelectedIds(nextIds)
      setSelected(
        nextIds.includes(id) ? selectedStateFromElement(element) : null,
      )
    },
    [getDoc, selectedIds],
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
    setSelectedIds([])
    setFrameRevision((current) => current + 1)
  }, [getDoc])

  useEffect(() => {
    setDraftKey((current) => current + 1)
    setDirty(false)
    setLastSavedMockup(null)
    setAnnotations(
      extractStructuredMockupAnnotations(mockup.content, mockup.metadata),
    )
  }, [mockup.content, mockup.metadata, mockup.mockup_id])

  useEffect(() => {
    const doc = getDoc()
    if (!doc?.body) return

    const isEditableTarget = (
      target: HTMLElement | null,
    ): target is HTMLElement =>
      Boolean(target && target !== doc.body && target !== doc.documentElement)

    const onPointerOver = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null
      if (!isEditableTarget(target)) return
      target.classList.add(HOVER_CLASS)
    }

    const onPointerOut = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null
      if (!target) return
      target.classList.remove(HOVER_CLASS)
    }

    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (!isEditableTarget(target)) return
      event.preventDefault()
      event.stopPropagation()
      selectElement(target, event.shiftKey || event.metaKey || event.ctrlKey)
      if (mode === 'note') {
        setNoteText(target.dataset.sfMockNoteText ?? '')
      }
    }

    const onPointerDown = (event: PointerEvent) => {
      if (mode !== 'move') return
      const target = event.target as HTMLElement | null
      if (!isEditableTarget(target)) return
      event.preventDefault()
      event.stopPropagation()
      const targetId = target.dataset.sfEditorId
      if (!targetId) return
      const selectedForDrag: HTMLElement[] =
        selectedIds.includes(targetId) && selectedIds.length > 1
          ? getSelectedElements()
          : [target]
      selectElement(target, event.shiftKey || event.metaKey || event.ctrlKey)
      selectedForDrag.forEach((element) => {
        element.style.position ||= 'relative'
        element.style.zIndex ||= '2'
      })
      dragRef = {
        elements: selectedForDrag.map((element) => ({
          element,
          baseX: Number.parseFloat(element.dataset.sfOffsetX ?? '0') || 0,
          baseY: Number.parseFloat(element.dataset.sfOffsetY ?? '0') || 0,
        })),
        startX: event.clientX,
        startY: event.clientY,
      }
    }

    const onPointerMove = (event: PointerEvent) => {
      if (!dragRef) return
      const d = dragRef
      d.elements.forEach(({ element, baseX, baseY }) => {
        const x = Math.round(baseX + event.clientX - d.startX)
        const y = Math.round(baseY + event.clientY - d.startY)
        element.dataset.sfOffsetX = String(x)
        element.dataset.sfOffsetY = String(y)
        element.style.transform = `translate(${x}px, ${y}px)`
      })
      setDirty(true)
    }

    const onPointerUp = () => {
      clearDragState()
      refreshSelected()
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Delete' && event.key !== 'Backspace') return
      const elements = getSelectedElements()
      if (!elements.length) return
      event.preventDefault()
      removeElements(elements)
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
    frameRevision,
    getDoc,
    getSelectedElements,
    mode,
    refreshSelected,
    selectElement,
    selectedIds,
  ])

  const serializeDraft = useCallback(
    () => serializeDraftDocument(getDoc(), content),
    [content, getDoc],
  )

  const saveMutation = useMutation({
    mutationFn: async () => {
      const draftContent = serializeDraft()
      const summary = buildEditorSummary(
        mockup,
        annotations,
        dirty,
        draftContent,
      )
      const metadata = buildEditorMetadata(mockup, annotations, draftContent)
      return createMockup(
        projectId,
        buildVersionPayload(mockup, draftContent, summary, metadata),
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

  const updateSelectedText = useCallback(
    (value: string) => {
      const element = getSelectedElement()
      if (!element) return
      element.textContent = value
      element.dataset.sfMockNoteText = element.classList.contains(
        'sf-mock-note',
      )
        ? value
        : (element.dataset.sfMockNoteText ?? '')
      if (element.dataset.sfMockNoteId) {
        setAnnotations((current) =>
          current.map((item) =>
            item.id === element.dataset.sfMockNoteId
              ? { ...item, note: value }
              : item,
          ),
        )
      }
      setSelected((current) =>
        current ? { ...current, text: value } : current,
      )
      setDirty(true)
    },
    [getSelectedElement],
  )

  const updateStyle = useCallback(
    (key: EditableStyleKey, value: string) => {
      const element = getSelectedElement()
      if (!element) return
      element.style[key] = value
      setSelected((current) =>
        current ? { ...current, [key]: value } : current,
      )
      setDirty(true)
    },
    [getSelectedElement],
  )

  const removeSelected = () => {
    const elements = getSelectedElements()
    if (!elements.length) return
    const removedNoteIds = elements
      .map((element) => element.dataset.sfMockNoteId)
      .filter((id): id is string => Boolean(id))
    elements.forEach((element) => element.remove())
    if (removedNoteIds.length) {
      setAnnotations((current) =>
        current.filter((item) => !removedNoteIds.includes(item.id ?? '')),
      )
    }
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
    const annotation: MockupAnnotation = {
      id: `ann-${Date.now()}`,
      note,
      element_path: buildMockupElementPath(element),
      element_label: describeMockupElement(element),
      rect: {
        left: Math.round(rect.left),
        top: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      created_at: new Date().toISOString(),
      source: 'surface-editor',
    }
    const bubble = doc.createElement('div')
    bubble.className = 'sf-mock-note'
    bubble.dataset.sfMockNoteText = note
    bubble.dataset.sfMockNoteId = annotation.id ?? ''
    bubble.dataset.sfMockTargetPath = annotation.element_path ?? ''
    bubble.textContent = note
    bubble.style.left = `${Math.max(12, rect.right + doc.defaultView!.scrollX + 52)}px`
    bubble.style.top = `${Math.max(12, rect.top + doc.defaultView!.scrollY)}px`
    doc.body.appendChild(bubble)
    bubble.dataset.sfEditorId = `note-${Date.now()}`
    setAnnotations((current) => [...current, annotation].slice(-20))
    selectElement(bubble)
    setDirty(true)
  }

  const sendToJenny = () => {
    const draftContent = serializeDraft()
    const savedMockup = lastSavedMockup ?? undefined
    const summary = [
      buildEditorSummary(mockup, annotations, dirty, draftContent),
      '',
      `Current artifact summary: ${summarizeMockupForWorkContext(savedMockup ?? mockup)}`,
      'Full HTML is stored in the Design artifact and should be fetched only when needed.',
    ].join('\n')
    onSendToJenny?.({
      sourceMockup: mockup,
      savedMockup,
      summary,
    })
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <EditorToolbar
            mode={mode}
            compareMode={compareMode}
            dirty={dirty}
            canSendToJenny={Boolean(onSendToJenny)}
            isSaving={saveMutation.isPending}
            onModeChange={setMode}
            onCompareModeChange={setCompareMode}
            onSendToJenny={sendToJenny}
            onSave={() => saveMutation.mutate()}
          />

          <SurfaceFrames
            compareMode={compareMode}
            content={content}
            mockup={mockup}
            draftKey={draftKey}
            iframeRef={iframeRef}
            onLoad={prepareDocument}
          />
        </div>

        <SurfaceInspector
          selected={selected}
          selectedCount={selectedIds.length}
          noteText={noteText}
          notes={notes}
          onTextChange={updateSelectedText}
          onMoveSibling={moveSelectedSibling}
          onStyleChange={updateStyle}
          onNoteTextChange={setNoteText}
          onAddNote={addNote}
          onRemoveSelected={removeSelected}
        />
      </div>
    </div>
  )
}
