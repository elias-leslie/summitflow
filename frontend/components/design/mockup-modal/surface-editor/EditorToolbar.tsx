'use client'

import clsx from 'clsx'
import { Save, Send } from 'lucide-react'
import {
  COMPARE_BUTTON_ACTIVE,
  COMPARE_BUTTON_BASE,
  COMPARE_BUTTON_IDLE,
  COMPARE_MODES,
  MODE_BUTTONS,
  TOOLBAR_BUTTON_ACTIVE,
  TOOLBAR_BUTTON_BASE,
  TOOLBAR_BUTTON_IDLE,
} from './constants'
import type { ToolbarProps } from './types'

export function EditorToolbar({
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
