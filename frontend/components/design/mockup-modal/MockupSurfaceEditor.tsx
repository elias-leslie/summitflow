'use client'

import { EditorToolbar } from './surface-editor/EditorToolbar'
import { SurfaceFrames } from './surface-editor/SurfaceFrames'
import { SurfaceInspector } from './surface-editor/SurfaceInspector'
import type { MockupSurfaceEditorProps } from './surface-editor/types'
import { useSurfaceEditor } from './surface-editor/useSurfaceEditor'

export function MockupSurfaceEditor({
  mockup,
  projectId,
  onSaved,
  onSendToJenny,
}: MockupSurfaceEditorProps) {
  const {
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
    isSaving,
    actions,
    prepareDocument,
  } = useSurfaceEditor(mockup, projectId, onSaved, onSendToJenny)

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <EditorToolbar
            mode={mode}
            compareMode={compareMode}
            dirty={dirty}
            canSendToJenny={Boolean(onSendToJenny)}
            isSaving={isSaving}
            onModeChange={setMode}
            onCompareModeChange={setCompareMode}
            onSendToJenny={actions.sendToJenny}
            onSave={actions.save}
          />

          <SurfaceFrames
            compareMode={compareMode}
            content={mockup.content ?? ''}
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
          onTextChange={actions.updateSelectedText}
          onMoveSibling={actions.moveSelectedSibling}
          onStyleChange={actions.updateStyle}
          onNoteTextChange={setNoteText}
          onAddNote={actions.addNote}
          onRemoveSelected={actions.removeSelected}
        />
      </div>
    </div>
  )
}
