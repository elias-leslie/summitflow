import { FolderKanban } from 'lucide-react'

interface SidebarHeaderProps {
  isCollapsed: boolean
}

export function SidebarHeader({ isCollapsed }: SidebarHeaderProps) {
  if (isCollapsed) {
    return (
      <div className="flex items-center justify-center py-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-outrun-500/20 bg-outrun-500/10 shadow-[0_16px_36px_-30px_rgba(255,0,102,0.9)]">
          <FolderKanban className="h-5 w-5 text-outrun-400" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3 px-3 py-4">
      <div className="eyebrow">Project lanes</div>
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-outrun-500/20 bg-outrun-500/10 shadow-[0_16px_36px_-30px_rgba(255,0,102,0.9)]">
          <FolderKanban className="h-5 w-5 text-outrun-400" />
        </div>
        <div className="min-w-0">
          <div className="display text-sm font-semibold text-slate-100">
            Projects
          </div>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            Keep repo context, task surfaces, and lane state within reach.
          </p>
        </div>
      </div>
    </div>
  )
}
