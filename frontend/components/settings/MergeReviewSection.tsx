import { clsx } from 'clsx'
import { GitMerge } from 'lucide-react'
import type { AutonomousExecutionSettings } from '@/lib/api'
import { Label } from '../ui/label'

interface MergeReviewSectionProps {
  settings: AutonomousExecutionSettings
  isPending: boolean
  onAutoMergeToggle: () => void
  onRequireReviewToggle: () => void
}

export function MergeReviewSection({
  settings,
  isPending,
  onAutoMergeToggle,
  onRequireReviewToggle,
}: MergeReviewSectionProps) {
  return (
    <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-6">
      <h3 className="text-base font-medium text-slate-100 flex items-center gap-2">
        <GitMerge className="w-4 h-4 text-slate-400" />
        Merge & Review
      </h3>

      {/* Auto-Merge Enabled */}
      <div>
        <div className="flex items-center justify-between">
          <div>
            <Label className="text-slate-200 block">
              Auto-Merge Enabled
            </Label>
            <p className="text-xs text-slate-400 mt-1">
              Enable automatic merging of completed tasks
            </p>
          </div>
          <button
            onClick={onAutoMergeToggle}
            disabled={isPending}
            className={clsx(
              'relative w-12 h-6 rounded-full transition-colors',
              settings.auto_merge_enabled ? 'bg-phosphor-500' : 'bg-slate-600',
            )}
          >
            <span
              className={clsx(
                'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                settings.auto_merge_enabled ? 'translate-x-7' : 'translate-x-1',
              )}
            />
          </button>
        </div>
      </div>

      {/* Require Review */}
      <div>
        <div className="flex items-center justify-between">
          <div>
            <Label className="text-slate-200 block">
              Require AI Review
            </Label>
            <p className="text-xs text-slate-400 mt-1">
              Always run AI review before merge (even if auto-merge enabled)
            </p>
          </div>
          <button
            onClick={onRequireReviewToggle}
            disabled={isPending}
            className={clsx(
              'relative w-12 h-6 rounded-full transition-colors',
              settings.require_review ? 'bg-phosphor-500' : 'bg-slate-600',
            )}
          >
            <span
              className={clsx(
                'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                settings.require_review ? 'translate-x-7' : 'translate-x-1',
              )}
            />
          </button>
        </div>
      </div>
    </div>
  )
}
