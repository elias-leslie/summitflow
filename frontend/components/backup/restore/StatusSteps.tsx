import { CheckCircle2, Loader2, XCircle } from 'lucide-react'

export function RestoringStep() {
  return (
    <div className="py-8 text-center">
      <Loader2 className="w-12 h-12 text-phosphor-400 animate-spin mx-auto mb-4" />
      <h3 className="text-lg font-medium text-slate-200 mb-2">Restoring...</h3>
      <p className="text-sm text-slate-400">
        Please wait while your data is being restored.
        <br />
        This may take several minutes.
      </p>
    </div>
  )
}

export function SuccessStep() {
  return (
    <div className="py-8 text-center">
      <div className="w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
        <CheckCircle2 className="w-8 h-8 text-green-400" />
      </div>
      <h3 className="text-lg font-medium text-slate-200 mb-2">
        Restore Started
      </h3>
      <p className="text-sm text-slate-400">
        The restore process has been queued.
        <br />
        Your data will be restored shortly.
      </p>
    </div>
  )
}

interface ErrorStepProps {
  errorMessage: string | null
}

export function ErrorStep({ errorMessage }: ErrorStepProps) {
  return (
    <div className="py-8 text-center">
      <div className="w-16 h-16 bg-red-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
        <XCircle className="w-8 h-8 text-red-400" />
      </div>
      <h3 className="text-lg font-medium text-slate-200 mb-2">
        Restore Failed
      </h3>
      <p className="text-sm text-red-400">{errorMessage}</p>
    </div>
  )
}
