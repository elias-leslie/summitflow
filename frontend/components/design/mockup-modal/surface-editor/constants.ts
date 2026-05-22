import { Code2, Grip, MessageSquarePlus, MousePointer2 } from 'lucide-react'
import type { CompareMode, EditableStyleKey, EditorMode } from './types'

export const EDITOR_STYLE_ID = 'sf-mock-editor-style'
export const SELECTED_CLASS = 'sf-editor-selected'
export const HOVER_CLASS = 'sf-editor-hover'

export const COMPARE_MODES: CompareMode[] = ['current', 'split', 'original']

export const STYLE_FIELDS: Array<{
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

export const MODE_BUTTONS: Array<{
  value: EditorMode
  label: string
  Icon: typeof MousePointer2
}> = [
  { value: 'inspect', label: 'Select', Icon: MousePointer2 },
  { value: 'text', label: 'Text', Icon: Code2 },
  { value: 'move', label: 'Move', Icon: Grip },
  { value: 'note', label: 'Note', Icon: MessageSquarePlus },
]

export const editorCss = `
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

export const TOOLBAR_BUTTON_BASE =
  'inline-flex h-8 items-center gap-1.5 rounded border px-2 text-xs transition-colors'
export const TOOLBAR_BUTTON_ACTIVE =
  'border-phosphor-500/50 bg-phosphor-500/12 text-phosphor-200'
export const TOOLBAR_BUTTON_IDLE =
  'border-slate-700 bg-slate-950/70 text-slate-400 hover:border-slate-600 hover:text-slate-200'
export const COMPARE_BUTTON_BASE =
  'h-8 rounded border px-2 text-xs capitalize transition-colors'
export const COMPARE_BUTTON_ACTIVE =
  'border-slate-500 bg-slate-800 text-slate-100'
export const COMPARE_BUTTON_IDLE =
  'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'
