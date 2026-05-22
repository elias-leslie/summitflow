'use client'

import {
  ArrowDown,
  ArrowUp,
  Eye,
  MessageSquarePlus,
  Trash2,
} from 'lucide-react'
import { STYLE_FIELDS } from './constants'
import type { InspectorProps } from './types'

export function SurfaceInspector({
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
