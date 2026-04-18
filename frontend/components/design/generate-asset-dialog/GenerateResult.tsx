'use client'

import { Image as ImageIcon } from 'lucide-react'
import NextImage from 'next/image'
import {
  type GenerateDesignAssetResponse,
  getDesignAssetImageUrl,
} from '@/lib/api/design-assets'

interface GenerateResultProps {
  result: GenerateDesignAssetResponse
  projectId: string
  assetName: string
}

export function GenerateResult({
  result,
  projectId,
  assetName,
}: GenerateResultProps): React.ReactElement {
  if (!result.success || result.assets.length === 0) {
    return (
      <div className="text-sm text-red-400">
        Generation failed for {assetName}
      </div>
    )
  }

  const primaryAsset = result.assets[0]

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-phosphor-500">
        <ImageIcon className="h-4 w-4" />
        <span className="text-sm font-medium">
          Generated {result.assets.length} asset
          {result.assets.length === 1 ? '' : 's'} in{' '}
          {(result.generation_time_ms / 1000).toFixed(1)}s
        </span>
      </div>
      <div className="relative aspect-square overflow-hidden rounded-lg border border-slate-700">
        <NextImage
          src={getDesignAssetImageUrl(projectId, primaryAsset.asset_id)}
          alt={assetName}
          fill
          className="object-contain"
          unoptimized
        />
      </div>
      {result.assets.length > 1 && (
        <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3 text-sm text-slate-300">
          {result.assets.map((asset) => (
            <p key={asset.asset_id}>
              {asset.name} • {asset.asset_type.replace('_', ' ')}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
