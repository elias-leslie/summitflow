'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Image, Loader2, X } from 'lucide-react'
import { useState } from 'react'
import {
  type GenerateAssetResponse,
  generateAsset,
  getMockupImageUrl,
} from '@/lib/api/mockups'

const ASSET_TYPES = [
  { value: 'sprite', label: 'Sprite' },
  { value: 'sheet', label: 'Sprite Sheet' },
  { value: 'illustration', label: 'Illustration' },
  { value: 'icon', label: 'Icon' },
] as const

const IMAGE_MODELS = [
  {
    id: 'gemini-3-pro-image-preview',
    name: 'Pro Image',
    hint: 'Best quality',
  },
  {
    id: 'gemini-2.5-flash-image',
    name: 'Nano Banana',
    hint: 'Fast',
  },
  {
    id: 'gemini-3.1-flash-image-preview',
    name: 'Nano Banana 2',
    hint: 'Fastest',
  },
] as const

const SIZES = ['512x512', '1024x1024', '1920x1080'] as const

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
  const [mockupType, setMockupType] = useState('sprite')
  const [model, setModel] = useState<string>(IMAGE_MODELS[0].id)
  const [size, setSize] = useState<string>('1024x1024')
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
        queryClient.invalidateQueries({
          queryKey: ['mockup-stats', projectId],
        })
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
    setMockupType('sprite')
    setModel(IMAGE_MODELS[0].id)
    setSize('1024x1024')
    setStyle('')
    setResult(null)
    mutation.reset()
    onOpenChange(false)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/80" onClick={handleClose} />

      {/* Dialog */}
      <div className="relative bg-slate-900 rounded-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <Image className="w-5 h-5 text-outrun-400" />
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

        {/* Content */}
        <div className="p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Prompt */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Prompt
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Describe the asset you want to generate..."
                rows={3}
                disabled={mutation.isPending}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-outrun-500 resize-none"
              />
            </div>

            {/* Name */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. coco-idle-pose"
                disabled={mutation.isPending}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-outrun-500"
              />
            </div>

            {/* Type + Size row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  Type
                </label>
                <select
                  value={mockupType}
                  onChange={(e) => setMockupType(e.target.value)}
                  disabled={mutation.isPending}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-outrun-500"
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
                  onChange={(e) => setSize(e.target.value)}
                  disabled={mutation.isPending}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-outrun-500"
                >
                  {SIZES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Model selector */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Model
              </label>
              <div className="grid grid-cols-3 gap-2">
                {IMAGE_MODELS.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setModel(m.id)}
                    disabled={mutation.isPending}
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

            {/* Style (optional) */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Style{' '}
                <span className="text-slate-500 font-normal">(optional)</span>
              </label>
              <input
                type="text"
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                placeholder="e.g. hand-drawn cartoon, bold outlines"
                disabled={mutation.isPending}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-outrun-500"
              />
            </div>

            {/* Actions */}
            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={handleClose}
                disabled={mutation.isPending}
                className="px-4 py-2 text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={
                  !prompt.trim() || !name.trim() || mutation.isPending
                }
                className="btn-primary flex items-center gap-2 disabled:opacity-50"
              >
                {mutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Image className="w-4 h-4" />
                    Generate
                  </>
                )}
              </button>
            </div>
          </form>

          {/* Result */}
          {result && (
            <div className="mt-6 border-t border-slate-800 pt-6">
              {result.success ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-phosphor-500">
                    <Image className="w-4 h-4" />
                    <span className="text-sm font-medium">
                      Generated in {(result.generation_time_ms / 1000).toFixed(1)}s
                      using {result.model_used}
                    </span>
                  </div>
                  {result.mockup_id && (
                    <div className="rounded-lg overflow-hidden border border-slate-700">
                      <img
                        src={getMockupImageUrl(projectId, result.mockup_id)}
                        alt={name}
                        className="w-full h-auto"
                      />
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-red-400 text-sm">
                  Generation failed: {result.error}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
