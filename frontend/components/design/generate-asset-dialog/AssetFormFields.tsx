'use client'

import { ASSET_TYPES, IMAGE_MODELS, SIZES } from './constants'

const INPUT_CLASS =
  'w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-outrun-500'

const SELECT_CLASS =
  'w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-outrun-500'

interface AssetFormFieldsProps {
  prompt: string
  name: string
  mockupType: string
  model: string
  size: string
  style: string
  isPending: boolean
  onPromptChange: (v: string) => void
  onNameChange: (v: string) => void
  onMockupTypeChange: (v: string) => void
  onModelChange: (v: string) => void
  onSizeChange: (v: string) => void
  onStyleChange: (v: string) => void
}

export function AssetFormFields({
  prompt,
  name,
  mockupType,
  model,
  size,
  style,
  isPending,
  onPromptChange,
  onNameChange,
  onMockupTypeChange,
  onModelChange,
  onSizeChange,
  onStyleChange,
}: AssetFormFieldsProps) {
  return (
    <>
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Prompt
        </label>
        <textarea
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          placeholder="Describe the asset you want to generate..."
          rows={3}
          disabled={isPending}
          className={`${INPUT_CLASS} resize-none`}
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Name
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="e.g. coco-idle-pose"
          disabled={isPending}
          className={INPUT_CLASS}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Type
          </label>
          <select
            value={mockupType}
            onChange={(e) => onMockupTypeChange(e.target.value)}
            disabled={isPending}
            className={SELECT_CLASS}
          >
            {ASSET_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Size
          </label>
          <select
            value={size}
            onChange={(e) => onSizeChange(e.target.value)}
            disabled={isPending}
            className={SELECT_CLASS}
          >
            {SIZES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Model
        </label>
        <div className="grid grid-cols-3 gap-2">
          {IMAGE_MODELS.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => onModelChange(m.id)}
              disabled={isPending}
              className={`px-3 py-2 rounded-lg border text-sm transition-all ${
                model === m.id
                  ? 'bg-outrun-500/20 border-outrun-500/50 text-outrun-400'
                  : 'bg-slate-800 border-slate-700 text-slate-300 hover:text-white hover:border-slate-600'
              }`}
            >
              <div className="font-medium">{m.name}</div>
              <div className="text-xs text-slate-500">{m.hint}</div>
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Style{' '}
          <span className="text-slate-500 font-normal">(optional)</span>
        </label>
        <input
          type="text"
          value={style}
          onChange={(e) => onStyleChange(e.target.value)}
          placeholder="e.g. hand-drawn cartoon, bold outlines"
          disabled={isPending}
          className={INPUT_CLASS}
        />
      </div>
    </>
  )
}
