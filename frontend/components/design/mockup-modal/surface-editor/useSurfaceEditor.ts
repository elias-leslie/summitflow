import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { createMockup } from '@/lib/api/mockups'
import {
  buildMockupElementPath,
  describeMockupElement,
  extractMockupAnnotations,
  extractStructuredMockupAnnotations,
  type MockupAnnotation,
  summarizeMockupForWorkContext,
} from '@/lib/mockup-html'
import { getErrorMessage } from '@/lib/utils'
import {
  EDITOR_STYLE_ID,
  editorCss,
  HOVER_CLASS,
  SELECTED_CLASS,
} from './constants'
import { editorDom } from './editorDom'
import type {
  DragState,
  EditableStyleKey,
  Mockup,
  SelectedElementState,
  UseSurfaceEditorReturn,
} from './types'

// Module-level drag state (not React state — must survive re-renders without triggering them)
let dragRef: DragState | null = null

export function useSurfaceEditor(
  mockup: Mockup,
  projectId: string,
  onSaved?: (mockup: Mockup) => void,
  onSendToJenny?: (payload: {
    sourceMockup: Mockup
    savedMockup?: Mockup
    summary: string
  }) => void,
): UseSurfaceEditorReturn {
  const iframeRef = useRef<HTMLIFrameElement | null>(null)
  const queryClient = useQueryClient()

  const [mode, setMode] = useState<'inspect' | 'text' | 'move' | 'note'>(
    'inspect',
  )
  const [compareMode, setCompareMode] = useState<
    'current' | 'split' | 'original'
  >('current')
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
    () => editorDom.getElementByEditorId(getDoc(), selectedId),
    [getDoc, selectedId],
  )

  const getSelectedElements = useCallback(
    () => editorDom.getElementsByEditorIds(getDoc(), selectedIds),
    [getDoc, selectedIds],
  )

  const refreshSelected = useCallback(
    (id: string | null = selectedId) => {
      const element = editorDom.getElementByEditorId(getDoc(), id)
      setSelected(element ? editorDom.selectedStateFromElement(element) : null)
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
        editorDom.applySelection(doc, [])
        return
      }

      const id = element.dataset.sfEditorId
      if (!id) return
      const nextIds = editorDom.toggleSelectedIds(selectedIds, id, additive)
      editorDom.applySelection(doc, nextIds)
      setSelectedId(id)
      setSelectedIds(nextIds)
      setSelected(
        nextIds.includes(id)
          ? editorDom.selectedStateFromElement(element)
          : null,
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

    editorDom.getEditableElements(doc).forEach((element, index) => {
      element.dataset.sfEditorId = `el-${index}`
      element.classList.remove(SELECTED_CLASS, HOVER_CLASS)
    })
    setSelected(null)
    setSelectedId(null)
    setSelectedIds([])
    setFrameRevision((current) => current + 1)
  }, [getDoc])

  // Reset when mockup changes
  useEffect(() => {
    setDraftKey((current) => current + 1)
    setDirty(false)
    setLastSavedMockup(null)
    setAnnotations(
      extractStructuredMockupAnnotations(mockup.content, mockup.metadata),
    )
  }, [mockup.content, mockup.metadata, mockup.mockup_id])

  // Attach iframe event handlers
  useEffect(() => {
    const doc = getDoc()
    if (!doc?.body) return

    const isEditableTarget = (
      target: HTMLElement | null,
    ): target is HTMLElement =>
      Boolean(target && target !== doc.body && target !== doc.documentElement)

    const handlers = {
      onPointerOver(event: PointerEvent) {
        const target = event.target as HTMLElement | null
        if (!isEditableTarget(target)) return
        target.classList.add(HOVER_CLASS)
      },

      onPointerOut(event: PointerEvent) {
        const target = event.target as HTMLElement | null
        if (!target) return
        target.classList.remove(HOVER_CLASS)
      },

      onClick(event: MouseEvent) {
        const target = event.target as HTMLElement | null
        if (!isEditableTarget(target)) return
        event.preventDefault()
        event.stopPropagation()
        selectElement(target, event.shiftKey || event.metaKey || event.ctrlKey)
        if (mode === 'note') {
          setNoteText(target.dataset.sfMockNoteText ?? '')
        }
      },

      onPointerDown(event: PointerEvent) {
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
        for (const element of selectedForDrag) {
          element.style.position ||= 'relative'
          element.style.zIndex ||= '2'
        }
        dragRef = {
          elements: selectedForDrag.map((element) => ({
            element,
            baseX: Number.parseFloat(element.dataset.sfOffsetX ?? '0') || 0,
            baseY: Number.parseFloat(element.dataset.sfOffsetY ?? '0') || 0,
          })),
          startX: event.clientX,
          startY: event.clientY,
        }
      },

      onPointerMove(event: PointerEvent) {
        if (!dragRef) return
        const d = dragRef
        for (const { element, baseX, baseY } of d.elements) {
          const x = Math.round(baseX + event.clientX - d.startX)
          const y = Math.round(baseY + event.clientY - d.startY)
          element.dataset.sfOffsetX = String(x)
          element.dataset.sfOffsetY = String(y)
          element.style.transform = `translate(${x}px, ${y}px)`
        }
        setDirty(true)
      },

      onPointerUp() {
        dragRef = null
        refreshSelected()
      },

      onKeyDown(event: KeyboardEvent) {
        if (event.key !== 'Delete' && event.key !== 'Backspace') return
        const elements = getSelectedElements()
        if (!elements.length) return
        event.preventDefault()
        elements.forEach((element) => element.remove())
        selectElement(null)
        setDirty(true)
      },
    }

    doc.addEventListener('pointerover', handlers.onPointerOver)
    doc.addEventListener('pointerout', handlers.onPointerOut)
    doc.addEventListener('click', handlers.onClick, true)
    doc.addEventListener('pointerdown', handlers.onPointerDown, true)
    doc.addEventListener('pointermove', handlers.onPointerMove, true)
    doc.addEventListener('pointerup', handlers.onPointerUp, true)
    doc.addEventListener('keydown', handlers.onKeyDown)

    return () => {
      doc.removeEventListener('pointerover', handlers.onPointerOver)
      doc.removeEventListener('pointerout', handlers.onPointerOut)
      doc.removeEventListener('click', handlers.onClick, true)
      doc.removeEventListener('pointerdown', handlers.onPointerDown, true)
      doc.removeEventListener('pointermove', handlers.onPointerMove, true)
      doc.removeEventListener('pointerup', handlers.onPointerUp, true)
      doc.removeEventListener('keydown', handlers.onKeyDown)
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
    () => editorDom.serializeDraftDocument(getDoc(), content),
    [content, getDoc],
  )

  const saveMutation = useMutation({
    mutationFn: async () => {
      const draftContent = serializeDraft()
      const summary = editorDom.buildEditorSummary(
        mockup,
        annotations,
        dirty,
        draftContent,
      )
      const metadata = editorDom.buildEditorMetadata(
        mockup,
        annotations,
        draftContent,
      )
      return createMockup(
        projectId,
        editorDom.buildVersionPayload(mockup, draftContent, summary, metadata),
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

  const actions = {
    updateSelectedText(value: string) {
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

    updateStyle(key: EditableStyleKey, value: string) {
      const element = getSelectedElement()
      if (!element) return
      element.style[key] = value
      setSelected((current) =>
        current ? { ...current, [key]: value } : current,
      )
      setDirty(true)
    },

    removeSelected() {
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
    },

    moveSelectedSibling(direction: 'before' | 'after') {
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
    },

    addNote() {
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
    },

    save() {
      saveMutation.mutate()
    },

    sendToJenny() {
      const draftContent = serializeDraft()
      const savedMockup = lastSavedMockup ?? undefined
      const summary = [
        editorDom.buildEditorSummary(mockup, annotations, dirty, draftContent),
        '',
        `Current artifact summary: ${summarizeMockupForWorkContext(savedMockup ?? mockup)}`,
        'Full HTML is stored in the Design artifact and should be fetched only when needed.',
      ].join('\n')
      onSendToJenny?.({
        sourceMockup: mockup,
        savedMockup,
        summary,
      })
    },
  }

  return {
    iframeRef,
    mode,
    setMode,
    compareMode,
    setCompareMode,
    selected,
    selectedIds,
    noteText,
    setNoteText,
    dirty,
    notes,
    draftKey,
    isSaving: saveMutation.isPending,
    actions,
    prepareDocument,
  }
}
