'use client'

import type { ProjectPublishResponse } from '@/lib/api/git'

export function PublishResultBlock({
  result,
}: {
  result: ProjectPublishResponse
}) {
  return (
    <div
      role="status"
      className="rounded-md border border-slate-700 bg-slate-950/50 p-3 text-sm text-slate-200"
    >
      <p>
        {result.publication_complete
          ? 'Publication complete'
          : `Publication ${result.status}`}
      </p>
      {result.reason && (
        <p className="mt-1 text-xs text-slate-400">
          {result.reason.replaceAll('_', ' ')}
        </p>
      )}
      <p className="mt-1 break-all font-mono text-xs">
        Source {result.requested_source_commit}
      </p>
      <p className="mt-1 text-xs text-slate-400">
        {result.delivery?.uploaded_source
          ? 'Source uploaded'
          : 'Upload not confirmed'}{' '}
        · Evidence {result.evidence_recorded ? 'recorded' : 'not recorded'}
      </p>
      {result.delivery?.pull_request_state === 'pending' && (
        <p className="mt-1 text-xs text-slate-400">
          Pull request requirements pending
        </p>
      )}
      {result.delivery?.merged_source && (
        <p className="mt-1 break-all font-mono text-xs">
          Merged source {result.delivery.merged_source}
        </p>
      )}
      {result.ci?.optional_state && (
        <p className="mt-1 text-xs text-slate-400">
          Optional cloud checks: {result.ci.optional_state.replaceAll('_', ' ')}
        </p>
      )}
    </div>
  )
}
