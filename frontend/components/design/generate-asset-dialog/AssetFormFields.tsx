'use client'

import clsx from 'clsx'
import {
  ASSET_TYPES,
  BACKGROUND_MODES,
  IMAGE_MODELS,
  SIZES,
  WORKFLOWS,
} from './constants'

const INPUT_CLASS =
  'w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-outrun-500'

const SELECT_CLASS =
  'w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:ring-2 focus:ring-outrun-500'

interface AssetFormFieldsProps {
  prompt: string
  name: string
  mockupType: string
  workflow: string
  model: string
  size: string
  style: string
  negativePrompt: string
  variantCount: number
  background: string
  tags: string
  sheetColumns: string
  sheetRows: string
  frameWidth: string
  frameHeight: string
  animationLabels: string
  isPending: boolean
  onPromptChange: (v: string) => void
  onNameChange: (v: string) => void
  onMockupTypeChange: (v: string) => void
  onWorkflowChange: (v: string) => void
  onModelChange: (v: string) => void
  onSizeChange: (v: string) => void
  onStyleChange: (v: string) => void
  onNegativePromptChange: (v: string) => void
  onVariantCountChange: (v: number) => void
  onBackgroundChange: (v: string) => void
  onTagsChange: (v: string) => void
  onSheetColumnsChange: (v: string) => void
  onSheetRowsChange: (v: string) => void
  onFrameWidthChange: (v: string) => void
  onFrameHeightChange: (v: string) => void
  onAnimationLabelsChange: (v: string) => void
}

export function AssetFormFields({
  prompt,
  name,
  mockupType,
  workflow,
  model,
  size,
  style,
  negativePrompt,
  variantCount,
  background,
  tags,
  sheetColumns,
  sheetRows,
  frameWidth,
  frameHeight,
  animationLabels,
  isPending,
  onPromptChange,
  onNameChange,
  onMockupTypeChange,
  onWorkflowChange,
  onModelChange,
  onSizeChange,
  onStyleChange,
  onNegativePromptChange,
  onVariantCountChange,
  onBackgroundChange,
  onTagsChange,
  onSheetColumnsChange,
  onSheetRowsChange,
  onFrameWidthChange,
  onFrameHeightChange,
  onAnimationLabelsChange,
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
          className={clsx(INPUT_CLASS, 'resize-none')}
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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
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
            Workflow
          </label>
          <select
            value={workflow}
            onChange={(e) => onWorkflowChange(e.target.value)}
            disabled={isPending}
            className={SELECT_CLASS}
          >
            {WORKFLOWS.map((workflowOption) => (
              <option key={workflowOption.value} value={workflowOption.value}>
                {workflowOption.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
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
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Background
          </label>
          <select
            value={background}
            onChange={(e) => onBackgroundChange(e.target.value)}
            disabled={isPending}
            className={SELECT_CLASS}
          >
            {BACKGROUND_MODES.map((mode) => (
              <option key={mode.value} value={mode.value}>
                {mode.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Agent
        </label>
        <div className="grid grid-cols-3 gap-2">
          {IMAGE_MODELS.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => onModelChange(m.id)}
              disabled={isPending}
              className={clsx(
                'px-3 py-2 rounded-lg border text-sm transition-all',
                model === m.id
                  ? 'bg-outrun-500/20 border-outrun-500/50 text-outrun-400'
                  : 'bg-slate-800 border-slate-700 text-slate-300 hover:text-slate-100 hover:border-slate-600',
              )}
            >
              <div className="font-medium">{m.name}</div>
              <div className="text-xs text-slate-500">{m.hint}</div>
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Style <span className="text-slate-500 font-normal">(optional)</span>
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

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Negative Prompt
        </label>
        <input
          type="text"
          value={negativePrompt}
          onChange={(e) => onNegativePromptChange(e.target.value)}
          placeholder="e.g. blurry, extra limbs, text, watermark"
          disabled={isPending}
          className={INPUT_CLASS}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Variant Count
          </label>
          <input
            type="number"
            min={1}
            max={4}
            value={variantCount}
            onChange={(e) => onVariantCountChange(Number(e.target.value))}
            disabled={isPending}
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Tags
          </label>
          <input
            type="text"
            value={tags}
            onChange={(e) => onTagsChange(e.target.value)}
            placeholder="hero, enemy, ui"
            disabled={isPending}
            className={INPUT_CLASS}
          />
        </div>
      </div>

      {mockupType === 'sprite_sheet' && (
        <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-4 space-y-4">
          <p className="text-sm font-medium text-slate-100">
            Sprite Sheet Settings
          </p>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <input
              value={sheetColumns}
              onChange={(e) => onSheetColumnsChange(e.target.value)}
              placeholder="Columns"
              disabled={isPending}
              className={INPUT_CLASS}
            />
            <input
              value={sheetRows}
              onChange={(e) => onSheetRowsChange(e.target.value)}
              placeholder="Rows"
              disabled={isPending}
              className={INPUT_CLASS}
            />
            <input
              value={frameWidth}
              onChange={(e) => onFrameWidthChange(e.target.value)}
              placeholder="Frame Width"
              disabled={isPending}
              className={INPUT_CLASS}
            />
            <input
              value={frameHeight}
              onChange={(e) => onFrameHeightChange(e.target.value)}
              placeholder="Frame Height"
              disabled={isPending}
              className={INPUT_CLASS}
            />
          </div>
          <input
            value={animationLabels}
            onChange={(e) => onAnimationLabelsChange(e.target.value)}
            placeholder="idle, walk, attack, hit"
            disabled={isPending}
            className={INPUT_CLASS}
          />
        </div>
      )}
    </>
  )
}
