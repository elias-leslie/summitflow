'use client'

import { FolderTree, HeartPulse } from 'lucide-react'

interface ProjectPreviewPanelProps {
  projectId: string
  healthPreview: string
  normalizedRootPath: string
  syncAgentHubPermission: boolean
  permissionTier: string
  autoExecEnabled: boolean
}

export function ProjectPreviewPanel({
  projectId,
  healthPreview,
  normalizedRootPath,
  syncAgentHubPermission,
  permissionTier,
  autoExecEnabled,
}: ProjectPreviewPanelProps) {
  const agentHubDisplay = syncAgentHubPermission
    ? `${permissionTier}${autoExecEnabled ? ' + auto-exec' : ''}`
    : 'disabled'

  return (
    <aside className="space-y-3">
      <div className="card space-y-3 p-4">
        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
          Live preview
        </div>

        <div className="space-y-2 text-xs text-slate-400">
          <PreviewRow label="Project ID">
            {projectId || <span className="text-slate-600">not-set</span>}
          </PreviewRow>
          <PreviewRow label="Health Check">{healthPreview}</PreviewRow>
          <PreviewRow label="Root Path">
            {normalizedRootPath || (
              <span className="text-slate-600">not configured</span>
            )}
          </PreviewRow>
          <PreviewRow label="Agent Hub Access">{agentHubDisplay}</PreviewRow>
        </div>
      </div>

      <div className="card space-y-2 p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-200">
          <HeartPulse className="h-4 w-4 text-emerald-400" />
          Operational Coverage
        </div>
        <div className="space-y-3 text-xs text-slate-400">
          <p>
            Health checks start working as soon as the base URL and endpoint are
            correct.
          </p>
          <div className="flex items-start gap-2 rounded-lg border border-slate-800 bg-slate-950/50 p-3">
            <FolderTree className="mt-0.5 h-4 w-4 text-phosphor-400" />
            <div>
              <p className="text-slate-300">Root path unlocks the rest</p>
              <p className="mt-1">
                Without a repo path, SummitFlow can still track metadata, but
                file browsing and service discovery stay blind.
              </p>
            </div>
          </div>
        </div>
      </div>
    </aside>
  )
}

function PreviewRow({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
        {label}
      </span>
      <div className="mt-1 break-all rounded-md border border-slate-800/70 bg-slate-950/60 px-2 py-1.5 font-mono text-slate-200">
        {children}
      </div>
    </div>
  )
}
