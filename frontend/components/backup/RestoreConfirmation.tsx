'use client'

import { AlertTriangle, ArrowRight } from 'lucide-react'
import { useState } from 'react'
import { type Backup, restoreBackup } from '@/lib/api/backups'
import { StepIndicator } from './restore/StepIndicator'
import { PreviewStep } from './restore/PreviewStep'
import { ConfirmStep } from './restore/ConfirmStep'
import {
  RestoringStep,
  SuccessStep,
  ErrorStep,
} from './restore/StatusSteps'
import { RestoreFooter } from './restore/RestoreFooter'

type RestoreStep = 'preview' | 'confirm' | 'restoring' | 'success' | 'error'

interface RestoreConfirmationProps {
  backup: Backup
  projectId: string
  projectName: string
  onClose: () => void
  onSuccess?: () => void
}

export function RestoreConfirmation({
  backup,
  projectId,
  projectName,
  onClose,
  onSuccess,
}: RestoreConfirmationProps) {
  const [step, setStep] = useState<RestoreStep>('preview')
  const [confirmText, setConfirmText] = useState('')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleRestore = async () => {
    setStep('restoring')
    setErrorMessage(null)

    try {
      await restoreBackup(projectId, backup.id)
      setStep('success')
      onSuccess?.()
    } catch (err) {
      setStep('error')
      setErrorMessage(
        err instanceof Error
          ? err.message
          : 'Restore failed. Please try again.',
      )
    }
  }

  const handleContinue = () => setStep('confirm')
  const handleBack = () => {
    setStep('preview')
    setConfirmText('')
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-lg border border-slate-700 w-full max-w-lg">
        <div className="px-6 py-4 border-b border-slate-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-yellow-500/20 rounded-lg">
              <AlertTriangle className="w-5 h-5 text-yellow-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-100">
                Restore Backup
              </h2>
              <p className="text-sm text-slate-400">
                This will overwrite current data
              </p>
            </div>
          </div>

          {(step === 'preview' || step === 'confirm') && (
            <div className="flex items-center gap-4 mt-4">
              <StepIndicator
                stepNum={1}
                label="Preview"
                active={step === 'preview'}
                completed={step === 'confirm'}
              />
              <ArrowRight className="w-4 h-4 text-slate-600" />
              <StepIndicator
                stepNum={2}
                label="Confirm"
                active={step === 'confirm'}
                completed={false}
              />
            </div>
          )}
        </div>

        <div className="p-6">
          {step === 'preview' && <PreviewStep backup={backup} />}
          {step === 'confirm' && (
            <ConfirmStep
              projectName={projectName}
              confirmText={confirmText}
              onConfirmTextChange={setConfirmText}
            />
          )}
          {step === 'restoring' && <RestoringStep />}
          {step === 'success' && <SuccessStep />}
          {step === 'error' && <ErrorStep errorMessage={errorMessage} />}
        </div>

        <RestoreFooter
          step={step}
          projectName={projectName}
          confirmText={confirmText}
          onClose={onClose}
          onContinue={handleContinue}
          onBack={handleBack}
          onRestore={handleRestore}
        />
      </div>
    </div>
  )
}
