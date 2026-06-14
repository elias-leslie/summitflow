'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Image as ImageIcon, X } from 'lucide-react'
import { useState } from 'react'
import {
  type DesignAsset,
  type GenerateDesignAssetResponse,
  generateDesignAssets,
  importDesignAsset,
} from '@/lib/api/design-assets'
import { AssetFormFields } from './generate-asset-dialog/AssetFormFields'
import { AssetSubmitButtons } from './generate-asset-dialog/AssetSubmitButtons'
import {
  DEFAULT_MOCKUP_TYPE,
  DEFAULT_MODEL_ID,
  DEFAULT_SIZE,
} from './generate-asset-dialog/constants'
import { GenerateResult } from './generate-asset-dialog/GenerateResult'

interface GenerateAssetDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onGenerated?: (assets: DesignAsset[]) => void | Promise<void>
}

export function GenerateAssetDialog({
  projectId,
  open,
  onOpenChange,
  onGenerated,
}: GenerateAssetDialogProps) {
  const [prompt, setPrompt] = useState('')
  const [name, setName] = useState('')
  const [sourceMode, setSourceMode] = useState<'manual' | 'agent_hub'>('manual')
  const [manualFile, setManualFile] = useState<File | null>(null)
  const [mockupType, setMockupType] = useState(DEFAULT_MOCKUP_TYPE)
  const [workflow, setWorkflow] = useState('concept')
  const [model, setModel] = useState<string>(DEFAULT_MODEL_ID)
  const [size, setSize] = useState<string>(DEFAULT_SIZE)
  const [style, setStyle] = useState('')
  const [negativePrompt, setNegativePrompt] = useState('')
  const [variantCount, setVariantCount] = useState(1)
  const [background, setBackground] = useState('transparent')
  const [tags, setTags] = useState('')
  const [sheetColumns, setSheetColumns] = useState('4')
  const [sheetRows, setSheetRows] = useState('2')
  const [frameWidth, setFrameWidth] = useState('128')
  const [frameHeight, setFrameHeight] = useState('128')
  const [animationLabels, setAnimationLabels] = useState('idle,walk,attack,hit')
  const [result, setResult] = useState<GenerateDesignAssetResponse | null>(null)
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: async () => {
      const common = {
        prompt: prompt || 'Manual asset import',
        name,
        asset_type: mockupType,
        workflow,
        background,
        transparent_background: background === 'transparent',
        tags: parseCsv(tags),
        sheet_columns:
          mockupType === 'sprite_sheet' ? Number(sheetColumns) : undefined,
        sheet_rows:
          mockupType === 'sprite_sheet' ? Number(sheetRows) : undefined,
        frame_width:
          mockupType === 'sprite_sheet' ? Number(frameWidth) : undefined,
        frame_height:
          mockupType === 'sprite_sheet' ? Number(frameHeight) : undefined,
        animation_labels:
          mockupType === 'sprite_sheet' ? parseCsv(animationLabels) : undefined,
      }
      if (sourceMode === 'manual') {
        if (!manualFile) throw new Error('Manual import requires an image file')
        return importDesignAsset(projectId, {
          ...common,
          image_base64: await fileToBase64(manualFile),
          mime_type: manualFile.type || guessMimeType(manualFile.name),
          original_file_name: manualFile.name,
          metadata: {
            source_gate: 'manual-current-agent',
          },
        })
      }
      return generateDesignAssets(projectId, {
        ...common,
        model,
        size,
        style_prompt: style || undefined,
        negative_prompt: negativePrompt || undefined,
        variant_count: variantCount,
      })
    },
    onSuccess: async (data) => {
      setResult(data)
      if (data.success) {
        queryClient.invalidateQueries({
          queryKey: ['design-assets', projectId],
        })
        queryClient.invalidateQueries({
          queryKey: ['design-assets-stats', projectId],
        })
        await onGenerated?.(data.assets)
      }
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    if (sourceMode === 'manual' && !manualFile) return
    if (sourceMode === 'agent_hub' && !prompt.trim()) return
    setResult(null)
    mutation.mutate()
  }

  const handleClose = () => {
    setPrompt('')
    setName('')
    setSourceMode('manual')
    setManualFile(null)
    setMockupType(DEFAULT_MOCKUP_TYPE)
    setWorkflow('concept')
    setModel(DEFAULT_MODEL_ID)
    setSize(DEFAULT_SIZE)
    setStyle('')
    setNegativePrompt('')
    setVariantCount(1)
    setBackground('transparent')
    setTags('')
    setSheetColumns('4')
    setSheetRows('2')
    setFrameWidth('128')
    setFrameHeight('128')
    setAnimationLabels('idle,walk,attack,hit')
    setResult(null)
    mutation.reset()
    onOpenChange(false)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-slate-950/90 backdrop-blur-sm"
        onClick={handleClose}
        role="presentation"
      />

      <div className="relative bg-slate-900 rounded-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <ImageIcon className="w-5 h-5 text-outrun-400" />
            <h2 className="text-lg font-semibold text-slate-100 display">
              Add Game Asset
            </h2>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="p-2 text-slate-400 hover:text-slate-100 transition-colors"
            aria-label="Close dialog"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-4">
              <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">
                Design Source Gate
              </p>
              <p className="mt-2 text-sm text-slate-300">
                Ask the project lead first: should this asset be created by the
                current agent/user and imported manually, or generated by the
                Agent Hub image agent?
              </p>
              <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setSourceMode('manual')}
                  className={`rounded-lg border px-4 py-3 text-left transition ${
                    sourceMode === 'manual'
                      ? 'border-cyan-400 bg-cyan-500/15 text-cyan-100'
                      : 'border-slate-700 bg-slate-800 text-slate-300'
                  }`}
                >
                  <div className="font-medium">Manual / current agent</div>
                  <div className="text-xs text-slate-400">
                    Upload an image and put it into Asset Studio review.
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setSourceMode('agent_hub')}
                  className={`rounded-lg border px-4 py-3 text-left transition ${
                    sourceMode === 'agent_hub'
                      ? 'border-cyan-400 bg-cyan-500/15 text-cyan-100'
                      : 'border-slate-700 bg-slate-800 text-slate-300'
                  }`}
                >
                  <div className="font-medium">Agent Hub image agent</div>
                  <div className="text-xs text-slate-400">
                    Send a prompt to the configured image-generation agent.
                  </div>
                </button>
              </div>
            </div>

            {sourceMode === 'manual' && (
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  Image File
                </label>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/svg+xml"
                  disabled={mutation.isPending}
                  onChange={(event) =>
                    setManualFile(event.target.files?.[0] ?? null)
                  }
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100 file:mr-3 file:rounded-md file:border-0 file:bg-cyan-500/20 file:px-3 file:py-1 file:text-cyan-100"
                />
              </div>
            )}

            <AssetFormFields
              sourceMode={sourceMode}
              prompt={prompt}
              name={name}
              mockupType={mockupType}
              workflow={workflow}
              model={model}
              size={size}
              style={style}
              negativePrompt={negativePrompt}
              variantCount={variantCount}
              background={background}
              tags={tags}
              sheetColumns={sheetColumns}
              sheetRows={sheetRows}
              frameWidth={frameWidth}
              frameHeight={frameHeight}
              animationLabels={animationLabels}
              isPending={mutation.isPending}
              onPromptChange={setPrompt}
              onNameChange={setName}
              onMockupTypeChange={setMockupType}
              onWorkflowChange={setWorkflow}
              onModelChange={setModel}
              onSizeChange={setSize}
              onStyleChange={setStyle}
              onNegativePromptChange={setNegativePrompt}
              onVariantCountChange={setVariantCount}
              onBackgroundChange={setBackground}
              onTagsChange={setTags}
              onSheetColumnsChange={setSheetColumns}
              onSheetRowsChange={setSheetRows}
              onFrameWidthChange={setFrameWidth}
              onFrameHeightChange={setFrameHeight}
              onAnimationLabelsChange={setAnimationLabels}
            />
            <AssetSubmitButtons
              isPending={mutation.isPending}
              isDisabled={
                !name.trim() ||
                (sourceMode === 'manual' && !manualFile) ||
                (sourceMode === 'agent_hub' && !prompt.trim())
              }
              pendingLabel={
                sourceMode === 'manual' ? 'Importing...' : 'Generating...'
              }
              submitLabel={
                sourceMode === 'manual'
                  ? 'Import for Review'
                  : 'Generate with Agent Hub'
              }
              onCancel={handleClose}
            />
          </form>

          {result && (
            <div className="mt-6 border-t border-slate-800 pt-6">
              <GenerateResult
                result={result}
                projectId={projectId}
                assetName={name}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function parseCsv(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string') {
        reject(new Error('Failed to read image file'))
        return
      }
      resolve(result.split(',')[1] ?? '')
    }
    reader.onerror = () =>
      reject(reader.error ?? new Error('Failed to read image file'))
    reader.readAsDataURL(file)
  })
}

function guessMimeType(fileName: string): string {
  const lowerName = fileName.toLowerCase()
  if (lowerName.endsWith('.svg')) return 'image/svg+xml'
  if (lowerName.endsWith('.jpg') || lowerName.endsWith('.jpeg')) {
    return 'image/jpeg'
  }
  if (lowerName.endsWith('.webp')) return 'image/webp'
  return 'image/png'
}
