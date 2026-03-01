'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Image as ImageIcon, X } from 'lucide-react'
import { useState } from 'react'
import { type GenerateAssetResponse, generateAsset } from '@/lib/api/mockups'
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
}

export function GenerateAssetDialog({
  projectId,
  open,
  onOpenChange,
}: GenerateAssetDialogProps) {
  const [prompt, setPrompt] = useState('')
  const [name, setName] = useState('')
  const [mockupType, setMockupType] = useState(DEFAULT_MOCKUP_TYPE)
  const [model, setModel] = useState<string>(DEFAULT_MODEL_ID)
  const [size, setSize] = useState<string>(DEFAULT_SIZE)
  const [style, setStyle] = useState('')
  const [result, setResult] = useState<GenerateAssetResponse | null>(null)
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () =>
      generateAsset(projectId, {
        prompt,
        name,
        mockup_type: mockupType,
        model,
        size,
        style: style || undefined,
      }),
    onSuccess: (data) => {
      setResult(data)
      if (data.success) {
        queryClient.invalidateQueries({ queryKey: ['mockups', projectId] })
        queryClient.invalidateQueries({ queryKey: ['mockup-stats', projectId] })
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
    setModel(DEFAULT_MODEL_ID)
    setSize(DEFAULT_SIZE)
    setStyle('')
    setResult(null)
    mutation.reset()
    onOpenChange(false)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/80" onClick={handleClose} />

      <div className="relative bg-slate-900 rounded-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <ImageIcon className="w-5 h-5 text-outrun-400" />
            <h2 className="text-lg font-semibold text-white">
              Generate Game Asset
            </h2>
          </div>
          <button
            onClick={handleClose}
            className="p-2 text-slate-400 hover:text-white"
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
              model={model}
              size={size}
              style={style}
              isPending={mutation.isPending}
              onPromptChange={setPrompt}
              onNameChange={setName}
              onMockupTypeChange={setMockupType}
              onModelChange={setModel}
              onSizeChange={setSize}
              onStyleChange={setStyle}
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
