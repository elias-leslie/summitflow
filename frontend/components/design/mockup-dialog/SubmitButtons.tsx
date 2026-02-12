'use client'

import { Loader2, Scan } from 'lucide-react'

interface SubmitButtonsProps {
  isPending: boolean
  isDisabled: boolean
  onCancel: () => void
}

export function SubmitButtons({
  isPending,
  isDisabled,
  onCancel,
}: SubmitButtonsProps) {
  return (
    <div className="flex justify-end gap-3 pt-4">
      <button
        type="button"
        onClick={onCancel}
        className="btn-secondary"
        disabled={isPending}
      >
        Cancel
      </button>
      <button
        type="submit"
        disabled={isDisabled || isPending}
        className="btn-primary flex items-center gap-2"
      >
        {isPending ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Analyzing...
          </>
        ) : (
          <>
            <Scan className="w-4 h-4" />
            Analyze Page
          </>
        )}
      </button>
    </div>
  )
}
