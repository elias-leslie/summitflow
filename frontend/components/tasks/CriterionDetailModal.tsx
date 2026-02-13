'use client'

import {
  CheckCircle2,
  Clock,
  Loader2,
  Terminal,
  X,
} from 'lucide-react'
import { useState } from 'react'
import type { TaskAcceptanceCriterion } from '@/lib/api/tasks'

interface CriterionDetailModalProps {
  criterion: TaskAcceptanceCriterion
  isOpen: boolean
  onClose: () => void
  onVerify?: (criterionId: string, verifiedBy: 'human') => Promise<void>
}

const categoryColors: Record<string, { bg: string; text: string }> = {
  correctness: { bg: 'bg-blue-900/40', text: 'text-blue-400' },
  performance: { bg: 'bg-purple-900/40', text: 'text-purple-400' },
  security: { bg: 'bg-red-900/40', text: 'text-red-400' },
  quality: { bg: 'bg-emerald-900/40', text: 'text-emerald-400' },
}

const verifyByColors: Record<string, { bg: string; text: string }> = {
  test: { bg: 'bg-blue-900/40', text: 'text-blue-400' },
  opus: { bg: 'bg-purple-900/40', text: 'text-purple-400' },
  human: { bg: 'bg-amber-900/40', text: 'text-amber-400' },
  agent: { bg: 'bg-slate-700', text: 'text-slate-400' },
}

export function CriterionDetailModal({
  criterion,
  isOpen,
  onClose,
  onVerify,
}: CriterionDetailModalProps) {
  const [isVerifying, setIsVerifying] = useState(false)

  if (!isOpen) return null

  const criterionId = criterion.criterion_id || criterion.id
  const category = criterion.category || 'correctness'
  const verifyBy = criterion.verify_by || 'test'
  const canVerify =
    onVerify && !criterion.verified && verifyBy === 'human' && criterionId

  const handleVerify = async () => {
    if (!onVerify || !criterionId) return
    setIsVerifying(true)
    try {
      await onVerify(criterionId, 'human')
      onClose()
    } finally {
      setIsVerifying(false)
    }
  }

  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return ''
    return new Date(dateStr).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div
        className="relative w-full max-w-lg mx-4 bg-slate-800 border border-slate-700 rounded-lg shadow-2xl"
        data-testid="criterion-detail-modal"
      >
        {/* Header */}
        <div className="flex items-start justify-between p-4 border-b border-slate-700">
          <div className="flex items-center gap-3">
            {criterion.verified ? (
              <CheckCircle2 className="h-5 w-5 text-phosphor-400 flex-shrink-0" />
            ) : (
              <Clock className="h-5 w-5 text-slate-500 flex-shrink-0" />
            )}
            <div>
              <div className="text-xs text-slate-500 font-mono uppercase tracking-wider">
                {criterionId || 'Criterion'}
              </div>
              <span
                className={`inline-block mt-1 text-xs px-2 py-0.5 rounded ${categoryColors[category]?.bg || 'bg-slate-700'} ${categoryColors[category]?.text || 'text-slate-400'}`}
              >
                {category}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-500 hover:text-slate-300 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* Criterion Text */}
          <div>
            <div className="text-xs text-slate-500 uppercase tracking-wider mb-1.5">
              Criterion
            </div>
            <p className="text-sm text-slate-200 leading-relaxed">
              {criterion.criterion}
            </p>
          </div>

          {/* Verify Command */}
          {criterion.verify_command && (
            <div>
              <div className="flex items-center gap-2 mb-1.5">
                <Terminal className="h-3.5 w-3.5 text-slate-500" />
                <span className="text-xs text-slate-500 uppercase tracking-wider">
                  Verify Command
                </span>
              </div>
              <div className="bg-slate-900 border-l-2 border-slate-600 rounded-r">
                <code className="block p-3 text-xs text-slate-300 font-mono whitespace-pre-wrap break-all overflow-x-auto">
                  {criterion.verify_command}
                </code>
              </div>
            </div>
          )}

          {/* Verification Method & Status */}
          <div className="flex items-center justify-between pt-2 border-t border-slate-700/50">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">Verify via</span>
              <span
                className={`text-xs px-2 py-0.5 rounded ${verifyByColors[verifyBy]?.bg || 'bg-slate-700'} ${verifyByColors[verifyBy]?.text || 'text-slate-400'}`}
              >
                {verifyBy}
              </span>
            </div>

            {criterion.verified && criterion.verified_at && (
              <div className="text-xs text-slate-500">
                Verified {formatDate(criterion.verified_at)}
                {criterion.verified_by_who && (
                  <span className="text-slate-400">
                    {' '}
                    by {criterion.verified_by_who}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Footer - Verify Button */}
        {canVerify && (
          <div className="p-4 border-t border-slate-700 bg-slate-800/50">
            <button
              onClick={handleVerify}
              disabled={isVerifying}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-amber-600/20 hover:bg-amber-600/30 border border-amber-600/30 text-amber-400 rounded transition-colors disabled:opacity-50"
            >
              {isVerifying ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              Mark as Verified
            </button>
            <p className="text-xs text-slate-500 text-center mt-2">
              Manually confirm this criterion has been verified
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
