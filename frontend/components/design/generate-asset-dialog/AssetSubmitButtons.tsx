'use client'

import { Image as ImageIcon, Loader2 } from 'lucide-react'

interface AssetSubmitButtonsProps {
  isPending: boolean
  isDisabled: boolean
  onCancel: () => void
}

export function AssetSubmitButtons({
  isPending,
  isDisabled,
  onCancel,
}: AssetSubmitButtonsProps) {
  return (
    <div className="flex justify-end gap-3 pt-2">
      <button
        type="button"
        onClick={onCancel}
        disabled={isPending}
        className="px-4 py-2 text-slate-400 hover:text-white"
      >
        Cancel
      </button>
      <button
        type="submit"
        disabled={isDisabled || isPending}
        className="btn-primary flex items-center gap-2 disabled:opacity-50"
      >
        {isPending ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Generating...
          </>
        ) : (
          <>
            <ImageIcon className="w-4 h-4" />
            Generate
          </>
        )}
      </button>
    </div>
  )
}
