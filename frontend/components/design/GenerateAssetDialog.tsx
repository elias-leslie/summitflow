'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Image as ImageIcon, X } from 'lucide-react'
import { useState } from 'react'
import {
  generateDesignAssets,
  type DesignAsset,
  type GenerateDesignAssetResponse,
} from '@/lib/api/design-assets'
import { AssetFormFields } from './generate-asset-dialog/AssetFormFields'
import { AssetSubmitButtons } from './generate-asset-dialog/AssetSubmitButtons'
import { GenerateResult } from './generate-asset-dialog/GenerateResult'
import {
  DEFAULT_MODEL_ID,
  DEFAULT_MOCKUP_TYPE,
  DEFAULT_SIZE,
} from './generate-asset-dialog/constants'

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
    mutationFn: () =>
      generateDesignAssets(projectId, {
        prompt,
        name,
        asset_type: mockupType,
        workflow,
        model,
        size,
        style_prompt: style || undefined,
        negative_prompt: negativePrompt || undefined,
        background,
        transparent_background: background === 'transparent',
        variant_count: variantCount,
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
        sheet_columns:
          mockupType === 'sprite_sheet' ? Number(sheetColumns) : undefined,
        sheet_rows: mockupType === 'sprite_sheet' ? Number(sheetRows) : undefined,
        frame_width:
          mockupType === 'sprite_sheet' ? Number(frameWidth) : undefined,
        frame_height:
          mockupType === 'sprite_sheet' ? Number(frameHeight) : undefined,
        animation_labels:
          mockupType === 'sprite_sheet'
            ? animationLabels
                .split(',')
                .map((label) => label.trim())
                .filter(Boolean)
            : undefined,
      }),
    onSuccess: async (data) => {
      setResult(data)
      if (data.success) {
        queryClient.invalidateQueries({ queryKey: ['design-assets', projectId] })
        queryClient.invalidateQueries({
          queryKey: ['design-assets-stats', projectId],
        })
        await onGenerated?.(data.assets)
      }
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!prompt.trim() || !name.trim()) return
    setResult(null)
    mutation.mutate()
  }

  const handleClose = () => {
    setPrompt('')
    setName('')
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
      <div className="absolute inset-0 bg-black/80" onClick={handleClose} role="presentation" />

      <div className="relative bg-slate-900 rounded-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <ImageIcon className="w-5 h-5 text-outrun-400" />
            <h2 className="text-lg font-semibold text-slate-100">
              Generate Game Asset
            </h2>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="p-2 text-slate-400 hover:text-white"
            aria-label="Close dialog"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <AssetFormFields
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
              isDisabled={!prompt.trim() || !name.trim()}
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
