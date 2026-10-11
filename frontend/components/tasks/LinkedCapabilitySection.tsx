'use client'

import clsx from 'clsx'
import { Link2 } from 'lucide-react'

interface Capability {
  capability_id: string
  name: string
  criteria_passed: number
  criteria_total: number
}

interface LinkedCapabilitySectionProps {
  capability: Capability
}

export function LinkedCapabilitySection({
  capability,
}: LinkedCapabilitySectionProps) {
  const hasCriteria = capability.criteria_total > 0
  const allPassed =
    hasCriteria && capability.criteria_passed === capability.criteria_total
  const progressPct = hasCriteria
    ? (capability.criteria_passed / capability.criteria_total) * 100
    : 0

  return (
    <div>
      <h3 className="mb-3 text-sm font-medium text-slate-400 flex items-center gap-2">
        <Link2 className="h-4 w-4" />
        Linked Capability
      </h3>

      <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
        <div className="flex items-center justify-between mb-2">
          <div>
            <span className="mono text-xs text-slate-500">
              {capability.capability_id}
            </span>
            <h4 className="text-sm font-medium text-slate-100">
              {capability.name}
            </h4>
          </div>
        </div>

        {hasCriteria && (
          <div className="mt-3">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs text-slate-500">Criteria</span>
              <span
                className={clsx(
                  'text-xs mono font-medium',
                  allPassed ? 'text-phosphor-400' : 'text-slate-400',
                )}
              >
                {capability.criteria_passed}/{capability.criteria_total}
              </span>
            </div>
            <div className="h-1.5 w-full bg-slate-700 rounded-full overflow-hidden">
              <div
                className={clsx(
                  'h-full transition-all duration-300',
                  allPassed ? 'bg-phosphor-500' : 'bg-blue-500',
                )}
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
