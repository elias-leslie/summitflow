import { clsx } from 'clsx'
import { GitMerge } from 'lucide-react'
import type { AutonomousExecutionSettings } from '@/lib/api'
import { Label } from '../ui/label'

const MERGE_TIERS = [
  { value: 1, label: 'Tier 1', description: 'Simple fixes, formatting' },
  {
    value: 2,
    label: 'Tier 2',
    description: 'Standard changes, small features',
  },
  { value: 3, label: 'Tier 3', description: 'Complex changes, refactors' },
  { value: 4, label: 'Tier 4', description: 'Architecture, critical changes' },
]

interface MergeReviewSectionProps {
  settings: AutonomousExecutionSettings
  isPending: boolean
  onAutoMergeToggle: () => void
  onRequireReviewToggle: () => void
  onAutoMergeTiersChange: (tiers: number[]) => void
}

export function MergeReviewSection({
  settings,
  isPending,
  onAutoMergeToggle,
  onRequireReviewToggle,
  onAutoMergeTiersChange,
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
            <Label className="text-slate-200 block">Auto-Merge Enabled</Label>
            <p className="text-xs text-slate-400 mt-1">
              Enable automatic merging of completed tasks
            </p>
          </div>
          <button
            type="button"
            onClick={onAutoMergeToggle}
            disabled={isPending}
            aria-label={
              settings.auto_merge_enabled
                ? 'Disable auto-merge'
                : 'Enable auto-merge'
            }
            className={clsx(
              'relative w-12 h-6 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/40 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
              settings.auto_merge_enabled ? 'bg-phosphor-500' : 'bg-slate-600',
            )}
          >
            <span
              className={clsx(
                'absolute top-1 w-4 h-4 bg-slate-100 rounded-full transition-transform shadow-sm',
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
            <Label className="text-slate-200 block">Require AI Review</Label>
            <p className="text-xs text-slate-400 mt-1">
              Always run AI review before merge (even if auto-merge enabled)
            </p>
          </div>
          <button
            type="button"
            onClick={onRequireReviewToggle}
            disabled={isPending}
            aria-label={
              settings.require_review
                ? 'Disable required review'
                : 'Enable required review'
            }
            className={clsx(
              'relative w-12 h-6 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/40 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
              settings.require_review ? 'bg-phosphor-500' : 'bg-slate-600',
            )}
          >
            <span
              className={clsx(
                'absolute top-1 w-4 h-4 bg-slate-100 rounded-full transition-transform shadow-sm',
                settings.require_review ? 'translate-x-7' : 'translate-x-1',
              )}
            />
          </button>
        </div>
      </div>

      {/* Auto-Merge Tiers */}
      {settings.auto_merge_enabled && (
        <div>
          <Label className="text-slate-200 block mb-1">
            Auto-Merge Eligible Tiers
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            Select which task complexity tiers can auto-merge without human
            review
          </p>
          <div className="space-y-2">
            {MERGE_TIERS.map((tier) => {
              const isSelected = (settings.auto_merge_tiers ?? [1]).includes(
                tier.value,
              )
              return (
                <label
                  key={tier.value}
                  className={clsx(
                    'flex items-center gap-3 p-2 rounded-md cursor-pointer transition-colors',
                    isSelected
                      ? 'bg-phosphor-500/10'
                      : 'bg-transparent hover:bg-slate-700/50',
                    isPending && 'opacity-50 cursor-not-allowed',
                  )}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    disabled={isPending}
                    onChange={() => {
                      const current = settings.auto_merge_tiers ?? [1]
                      const updated = isSelected
                        ? current.filter((t) => t !== tier.value)
                        : [...current, tier.value].sort()
                      onAutoMergeTiersChange(updated)
                    }}
                    className="w-4 h-4 rounded border-slate-500 text-phosphor-500 focus:ring-phosphor-500 bg-slate-700"
                  />
                  <div>
                    <span className="text-sm text-slate-200">{tier.label}</span>
                    <span className="text-xs text-slate-400 ml-2">
                      {tier.description}
                    </span>
                  </div>
                </label>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
