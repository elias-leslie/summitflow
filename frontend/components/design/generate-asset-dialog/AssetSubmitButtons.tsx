'use client'

import { Image as ImageIcon, Loader2 } from 'lucide-react'

interface AssetSubmitButtonsProps {
  isPending: boolean
  isDisabled: boolean
  pendingLabel?: string
  submitLabel?: string
  onCancel: () => void
}

export function AssetSubmitButtons({
  isPending,
  isDisabled,
  pendingLabel = 'Generating...',
  submitLabel = 'Generate',
  onCancel,
}: AssetSubmitButtonsProps) {
  return (
    <div className="flex justify-end gap-3 pt-2">
      <button
        type="button"
        onClick={onCancel}
        disabled={isPending}
        className="px-4 py-2 text-slate-400 hover:text-slate-100"
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
            {pendingLabel}
          </>
        ) : (
          <>
            <ImageIcon className="w-4 h-4" />
            {submitLabel}
          </>
        )}
      </button>
    </div>
  )
}
