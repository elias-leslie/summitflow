import { FolderKanban } from 'lucide-react'

interface SidebarHeaderProps {
  isCollapsed: boolean
}

export function SidebarHeader({ isCollapsed }: SidebarHeaderProps) {
  if (isCollapsed) {
    return (
      <div className="flex items-center justify-center py-2.5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-outrun-500/20 bg-outrun-500/10">
          <FolderKanban className="h-4 w-4 text-outrun-400" />
        </div>
      </div>
    )
  }

  return (
    <div className="px-3 py-3">
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-outrun-500/20 bg-outrun-500/10">
          <FolderKanban className="h-4 w-4 text-outrun-400" />
        </div>
        <div className="min-w-0">
          <div className="display text-sm font-semibold text-slate-100">
            Projects
          </div>
          <p className="text-[10px] text-slate-500">
            Repo context and lane state
          </p>
        </div>
      </div>
    </div>
  )
}
