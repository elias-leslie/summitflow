import type { Mockup } from '@/lib/api/mockups'
import type { MockupAnnotation } from '@/lib/mockup-html'

export type EditorMode = 'inspect' | 'text' | 'move' | 'note'
export type CompareMode = 'current' | 'split' | 'original'
export type EditableStyleKey = keyof Pick<
  SelectedElementState,
  'color' | 'backgroundColor' | 'margin' | 'padding' | 'borderRadius'
>

export interface SelectedElementState {
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

export interface MockupSurfaceEditorProps {
  mockup: Mockup
  projectId: string
  onSaved?: (mockup: Mockup) => void
  onSendToJenny?: (payload: {
    sourceMockup: Mockup
    savedMockup?: Mockup
    summary: string
  }) => void
}

export interface ToolbarProps {
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

export interface SurfaceFrameProps {
  compareMode: CompareMode
  content: string
  mockup: Mockup
  draftKey: number
  iframeRef: React.RefObject<HTMLIFrameElement | null>
  onLoad: () => void
}

export interface InspectorProps {
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

export interface DragState {
  elements: Array<{ element: HTMLElement; baseX: number; baseY: number }>
  startX: number
  startY: number
}

export interface SurfaceEditorActions {
  updateSelectedText: (value: string) => void
  updateStyle: (key: EditableStyleKey, value: string) => void
  removeSelected: () => void
  moveSelectedSibling: (direction: 'before' | 'after') => void
  addNote: () => void
  sendToJenny: () => void
  save: () => void
}

export interface UseSurfaceEditorReturn {
  iframeRef: React.RefObject<HTMLIFrameElement | null>
  mode: EditorMode
  setMode: (mode: EditorMode) => void
  compareMode: CompareMode
  setCompareMode: (mode: CompareMode) => void
  selected: SelectedElementState | null
  selectedIds: string[]
  noteText: string
  setNoteText: (text: string) => void
  dirty: boolean
  notes: string[]
  draftKey: number
  isSaving: boolean
  actions: SurfaceEditorActions
  prepareDocument: () => void
}

export type { Mockup, MockupAnnotation }
