import { clsx } from 'clsx'
import { ArrowRight, RotateCcw } from 'lucide-react'

type RestoreStep = 'preview' | 'confirm' | 'restoring' | 'success' | 'error'

interface RestoreFooterProps {
  step: RestoreStep
  projectName: string
  confirmText: string
  onClose: () => void
  onContinue: () => void
  onBack: () => void
  onRestore: () => void
}

export function RestoreFooter({
  step,
  projectName,
  confirmText,
  onClose,
  onContinue,
  onBack,
  onRestore,
}: RestoreFooterProps) {
  const isConfirmValid = confirmText === projectName

  if (step === 'preview') {
    return (
      <div className="px-6 py-4 border-t border-slate-700 flex justify-between">
        <button
          onClick={onClose}
          className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={onContinue}
          className="flex items-center gap-2 px-4 py-2 text-sm bg-yellow-600 text-white
                     hover:bg-yellow-500 rounded-md transition-colors font-medium"
        >
          Continue
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    )
  }

  if (step === 'confirm') {
    return (
      <div className="px-6 py-4 border-t border-slate-700 flex justify-between">
        <button
          onClick={onBack}
          className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
        >
          Back
        </button>
        <button
          onClick={onRestore}
          disabled={!isConfirmValid}
          className={clsx(
            'flex items-center gap-2 px-4 py-2 text-sm rounded-md transition-colors font-medium',
            isConfirmValid
              ? 'bg-red-600 text-white hover:bg-red-500'
              : 'bg-slate-700 text-slate-500 cursor-not-allowed',
          )}
        >
          <RotateCcw className="w-4 h-4" />
          Restore Backup
        </button>
      </div>
    )
  }

  if (step === 'restoring') {
    return (
      <div className="px-6 py-4 border-t border-slate-700">
        <div className="w-full text-center">
          <span className="text-sm text-slate-500">Please wait...</span>
        </div>
      </div>
    )
  }

  if (step === 'success' || step === 'error') {
    return (
      <div className="px-6 py-4 border-t border-slate-700 flex justify-end">
        <button
          onClick={onClose}
          className="px-4 py-2 text-sm bg-slate-700 text-slate-200
                     hover:bg-slate-600 rounded-md transition-colors font-medium"
        >
          Close
        </button>
      </div>
    )
  }

  return null
}
