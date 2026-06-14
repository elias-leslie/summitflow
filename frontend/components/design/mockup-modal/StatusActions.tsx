'use client'

import {
  Archive,
  Box,
  CheckCircle2,
  Clock,
  Loader2,
  XCircle,
} from 'lucide-react'
import type { Mockup } from '@/lib/api/mockups'

interface StatusActionsProps {
  mockup: Mockup
  updating: boolean
  onStatusChange: (status: string) => void
}

export function StatusActions({
  mockup,
  updating,
  onStatusChange,
}: StatusActionsProps) {
  const nextStatus = (requestedStatus: string): string =>
    mockup.status === requestedStatus ? 'generated' : requestedStatus

  return (
    <div>
      <h3 className="text-sm font-medium text-slate-400 mb-2">Change Status</h3>
      <div className="flex flex-wrap gap-2">
        {mockup.status === 'generated' && (
          <button
            type="button"
            onClick={() => onStatusChange('pending_approval')}
            disabled={updating}
            className="btn-secondary flex items-center gap-2"
          >
            {updating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Clock className="w-4 h-4" />
            )}
            Submit for Review
          </button>
        )}
        {(mockup.status === 'generated' ||
          mockup.status === 'pending_approval' ||
          mockup.status === 'approved' ||
          mockup.status === 'rejected' ||
          mockup.status === 'archived') && (
          <>
            <button
              type="button"
              onClick={() => onStatusChange(nextStatus('approved'))}
              disabled={updating}
              className={statusActionClass(
                'approved',
                mockup.status === 'approved',
              )}
            >
              {updating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <CheckCircle2 className="w-4 h-4" />
              )}
              Approve
            </button>
            <button
              type="button"
              onClick={() => onStatusChange(nextStatus('rejected'))}
              disabled={updating}
              className={statusActionClass(
                'rejected',
                mockup.status === 'rejected',
              )}
            >
              {updating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <XCircle className="w-4 h-4" />
              )}
              Reject
            </button>
            <button
              type="button"
              onClick={() => onStatusChange(nextStatus('archived'))}
              disabled={updating}
              className={statusActionClass(
                'archived',
                mockup.status === 'archived',
              )}
            >
              {updating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Archive className="w-4 h-4" />
              )}
              Archive
            </button>
          </>
        )}
        {mockup.status === 'approved' && (
          <button
            type="button"
            onClick={() => onStatusChange('applied')}
            disabled={updating}
            className="btn-primary flex items-center gap-2"
          >
            {updating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Box className="w-4 h-4" />
            )}
            Mark as Applied
          </button>
        )}
      </div>
    </div>
  )
}

function statusActionClass(status: string, isActive: boolean): string {
  if (!isActive) {
    if (status === 'approved') {
      return 'btn-primary flex items-center gap-2'
    }
    if (status === 'rejected') {
      return 'btn-secondary text-rose-400 hover:bg-rose-500/10 flex items-center gap-2'
    }
    return 'btn-secondary text-amber-400 hover:bg-amber-500/10 flex items-center gap-2'
  }

  if (status === 'approved') {
    return 'rounded-lg border border-emerald-400/60 bg-emerald-500/15 px-3 py-2 text-sm font-medium text-emerald-100 disabled:opacity-100 flex items-center gap-2'
  }

  if (status === 'rejected') {
    return 'rounded-lg border border-rose-400/60 bg-rose-500/15 px-3 py-2 text-sm font-medium text-rose-100 disabled:opacity-100 flex items-center gap-2'
  }

  return 'rounded-lg border border-amber-400/60 bg-amber-500/15 px-3 py-2 text-sm font-medium text-amber-100 disabled:opacity-100 flex items-center gap-2'
}
