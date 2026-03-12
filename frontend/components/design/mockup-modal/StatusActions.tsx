'use client'

import { Box, CheckCircle2, Clock, Loader2, XCircle } from 'lucide-react'
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
          mockup.status === 'pending_approval') && (
          <>
            <button
              type="button"
              onClick={() => onStatusChange('approved')}
              disabled={updating}
              className="btn-primary flex items-center gap-2"
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
              onClick={() => onStatusChange('rejected')}
              disabled={updating}
              className="btn-secondary text-rose-400 hover:bg-rose-500/10 flex items-center gap-2"
            >
              {updating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <XCircle className="w-4 h-4" />
              )}
              Reject
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
