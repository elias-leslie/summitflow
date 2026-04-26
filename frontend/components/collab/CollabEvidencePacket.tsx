import { FileText } from 'lucide-react'
import type { CollabEvidencePacket as Packet } from '@/lib/api/collab'

interface CollabEvidencePacketProps {
  packet: Packet
}

export function CollabEvidencePacket({
  packet,
}: CollabEvidencePacketProps): React.ReactElement {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <FileText className="h-3.5 w-3.5 shrink-0 text-cyan-300" />
          <span className="truncate text-xs font-medium text-slate-100">
            {packet.title || packet.selector || packet.evidence_id}
          </span>
        </div>
        <span className="shrink-0 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-slate-400">
          {packet.token_estimate} tok
        </span>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-400">
        {packet.context_summary}
      </p>
      {packet.selector && (
        <div className="mt-2 truncate font-mono text-[11px] text-slate-500">
          {packet.selector}
        </div>
      )}
    </div>
  )
}
