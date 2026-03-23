'use client'

import { ExternalLink, Link2 } from 'lucide-react'
import Link from 'next/link'

interface Capability {
  capability_id: string
  name: string
  criteria_passed: number
  criteria_total: number
}

interface LinkedCapabilitySectionProps {
  capability: Capability
  projectId: string
}

export function LinkedCapabilitySection({
  capability,
  projectId,
}: LinkedCapabilitySectionProps) {
  const hasCriteria = capability.criteria_total > 0
  const allPassed =
    hasCriteria && capability.criteria_passed === capability.criteria_total
  const progressPct = hasCriteria
    ? (capability.criteria_passed / capability.criteria_total) * 100
    : 0

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2">
          <Link2 className="h-4 w-4" />
          Linked Capability
        </h3>
        <Link
          href={`/projects/${projectId}/components`}
          className="text-xs text-phosphor-400 hover:text-phosphor-300 flex items-center gap-1"
        >
          View Capabilities
          <ExternalLink className="h-3 w-3" />
        </Link>
      </div>

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
                className={`text-xs mono font-medium ${allPassed ? 'text-phosphor-400' : 'text-slate-400'}`}
              >
                {capability.criteria_passed}/{capability.criteria_total}
              </span>
            </div>
            <div className="h-1.5 w-full bg-slate-700 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all duration-300 ${allPassed ? 'bg-phosphor-500' : 'bg-blue-500'}`}
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
