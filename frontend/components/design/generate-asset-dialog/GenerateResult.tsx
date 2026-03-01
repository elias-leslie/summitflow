'use client'

import { Image as ImageIcon } from 'lucide-react'
import NextImage from 'next/image'
import type { GenerateAssetResponse } from '@/lib/api/mockups'
import { getMockupImageUrl } from '@/lib/api/mockups'

interface GenerateResultProps {
  result: GenerateAssetResponse
  projectId: string
  assetName: string
}

export function GenerateResult({
  result,
  projectId,
  assetName,
}: GenerateResultProps) {
  if (!result.success) {
    return (
      <div className="text-red-400 text-sm">
        Generation failed: {result.error}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-phosphor-500">
        <ImageIcon className="w-4 h-4" />
        <span className="text-sm font-medium">
          Generated in {(result.generation_time_ms / 1000).toFixed(1)}s using{' '}
          {result.model_used}
        </span>
      </div>
      {result.mockup_id && (
        <div className="relative rounded-lg overflow-hidden border border-slate-700 aspect-square">
          <NextImage
            src={getMockupImageUrl(projectId, result.mockup_id)}
            alt={assetName}
            fill
            className="object-contain"
            unoptimized
          />
        </div>
      )}
    </div>
  )
}
