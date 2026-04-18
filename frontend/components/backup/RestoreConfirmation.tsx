'use client'

import { useMutation } from '@tanstack/react-query'
import { RotateCcw } from 'lucide-react'
import { useState } from 'react'
import type { Backup } from '@/lib/api/backups'
import { restoreBackup, restoreSourceBackup } from '@/lib/api/backups'
import { ConfirmStep } from './restore/ConfirmStep'
import { PreviewStep } from './restore/PreviewStep'
import { RestoreFooter } from './restore/RestoreFooter'
import { ErrorStep, RestoringStep, SuccessStep } from './restore/StatusSteps'
import { StepIndicator } from './restore/StepIndicator'

type RestoreStep = 'preview' | 'confirm' | 'restoring' | 'success' | 'error'

interface RestoreConfirmationProps {
  backup: Backup
  projectId?: string
  sourceId?: string
  projectName: string
  onClose: () => void
  onSuccess: () => void
}

export function RestoreConfirmation({
  backup,
  projectId,
  sourceId,
  projectName,
  onClose,
  onSuccess,
}: RestoreConfirmationProps) {
  const [step, setStep] = useState<RestoreStep>('preview')
  const [confirmText, setConfirmText] = useState('')

  const restoreMutation = useMutation({
    mutationFn: () =>
      sourceId
        ? restoreSourceBackup(sourceId, backup.id)
        : restoreBackup(projectId!, backup.id),
    onSuccess: () => {
      setStep('success')
      onSuccess()
    },
    onError: () => {
      setStep('error')
    },
  })

  const handleContinue = () => {
    setStep('confirm')
  }

  const handleBack = () => {
    setStep('preview')
    setConfirmText('')
  }

  const handleRestore = () => {
    setStep('restoring')
    restoreMutation.mutate()
  }

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-700">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-yellow-500/20 rounded-lg flex items-center justify-center">
            <RotateCcw className="w-5 h-5 text-yellow-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-100">
              Restore Backup
            </h2>
            <p className="text-sm text-slate-400">
              Restore {projectName} from backup
            </p>
          </div>
        </div>
      </div>

      {/* Step Indicators */}
      {(step === 'preview' || step === 'confirm') && (
        <div className="px-6 py-3 border-b border-slate-700 flex gap-6">
          <StepIndicator
            stepNum={1}
            label="Preview"
            active={step === 'preview'}
            completed={step === 'confirm'}
          />
          <StepIndicator
            stepNum={2}
            label="Confirm"
            active={step === 'confirm'}
            completed={false}
          />
        </div>
      )}

      {/* Content */}
      <div className="px-6 py-5">
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
        {step === 'error' && (
          <ErrorStep
            errorMessage={
              restoreMutation.error instanceof Error
                ? restoreMutation.error.message
                : 'An unexpected error occurred'
            }
          />
        )}
      </div>

      {/* Footer */}
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
  )
}
