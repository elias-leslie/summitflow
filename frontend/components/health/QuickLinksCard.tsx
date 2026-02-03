import { AlertTriangle, Settings, Zap } from 'lucide-react'
import Link from 'next/link'

interface QuickLinksCardProps {
  projectId: string
}

export function QuickLinksCard({ projectId }: QuickLinksCardProps) {
  return (
    <div className="card rounded-xl p-4">
      <h3 className="text-sm font-semibold text-slate-300 mb-3">Quick Links</h3>
      <div className="space-y-2">
        <a
          href="http://localhost:8003"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-purple-400 transition"
        >
          <Zap className="w-4 h-4" />
          Agent Hub Memory
        </a>
        <Link
          href={`/projects/${projectId}?tab=tasks&status=blocked&taskType=bug`}
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-purple-400 transition"
        >
          <AlertTriangle className="w-4 h-4" />
          All Escalated Tasks
        </Link>
        <Link
          href={`/projects/${projectId}/settings`}
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-purple-400 transition"
        >
          <Settings className="w-4 h-4" />
          Configure Auto-Fix
        </Link>
      </div>
    </div>
  )
}
