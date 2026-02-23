import clsx from 'clsx'
import { ChevronDown, Settings2 } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { Project } from '@/lib/api'
import type { NavItemId } from './types'
import { projectNavItems } from './constants'
import { ProjectNavItem } from './ProjectNavItem'
import { useProjectPermissionTier } from './useProjectPermissionTier'

const TIER_BADGE_CONFIG = {
  off: { label: 'OFF', bg: 'bg-slate-600/30', text: 'text-slate-500', border: 'border-slate-600/40' },
  read: { label: 'R', bg: 'bg-blue-500/15', text: 'text-blue-400', border: 'border-blue-500/30' },
  write: { label: 'W', bg: 'bg-amber-500/15', text: 'text-amber-400', border: 'border-amber-500/30' },
  yolo: { label: 'Y', bg: 'bg-emerald-500/15', text: 'text-emerald-400', border: 'border-emerald-500/30' },
} as const

interface ProjectAccordionItemProps {
  project: Project
  isExpanded: boolean
  isActive: boolean
  activeTab: NavItemId | null
  onToggleExpand: () => void
  getProjectNavHref: (projectId: string, item: typeof projectNavItems[number]) => string
}

export function ProjectAccordionItem({
  project,
  isExpanded,
  isActive,
  activeTab,
  onToggleExpand,
  getProjectNavHref,
}: ProjectAccordionItemProps) {
  const pathname = usePathname()
  const tier = useProjectPermissionTier(project.id)
  const badge = tier ? TIER_BADGE_CONFIG[tier as keyof typeof TIER_BADGE_CONFIG] : null

  return (
    <div
      className="rounded-lg overflow-hidden"
      data-testid="project-accordion-item"
      data-expanded={isExpanded}
    >
      {/* Project header */}
      <button
        onClick={onToggleExpand}
        data-testid={`project-accordion-${project.id}`}
        className={clsx(
          'w-full flex items-center gap-2.5 px-3 py-2.5 transition-all duration-200 group',
          isActive ? 'bg-outrun-500/10' : 'hover:bg-slate-800/50',
        )}
      >
        {/* Project icon with health indicator */}
        <div className="relative flex-shrink-0">
          <div
            className={clsx(
              'w-8 h-8 rounded-lg flex items-center justify-center border transition-all duration-200',
              isActive
                ? 'bg-gradient-to-br from-outrun-500/20 to-pink-500/10 border-outrun-500/40'
                : 'bg-slate-800/50 border-slate-700/50 group-hover:border-slate-600',
            )}
          >
            <span
              className={clsx(
                'text-xs font-bold transition-colors',
                isActive
                  ? 'text-outrun-400'
                  : 'text-slate-400 group-hover:text-slate-300',
              )}
            >
              {project.name.charAt(0).toUpperCase()}
            </span>
          </div>
          {/* Health dot */}
          <div
            className={clsx(
              'absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-slate-900',
              project.health_status === 'healthy'
                ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]'
                : 'bg-slate-500',
            )}
          />
        </div>

        {/* Project name */}
        <div className="flex-1 min-w-0 text-left">
          <div
            className={clsx(
              'text-sm font-medium truncate transition-colors',
              isActive
                ? 'text-white'
                : 'text-slate-300 group-hover:text-white',
            )}
          >
            {project.name}
          </div>
        </div>

        {/* Permission tier badge */}
        {badge && (
          <span
            className={clsx(
              'flex-shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold leading-none border',
              badge.bg, badge.text, badge.border,
            )}
            title={`Permission tier: ${tier}`}
          >
            {badge.label}
          </span>
        )}

        {/* Expand chevron */}
        <ChevronDown
          className={clsx(
            'w-4 h-4 transition-all duration-250 flex-shrink-0',
            isExpanded
              ? 'rotate-180 text-outrun-400'
              : 'text-slate-500 group-hover:text-slate-400',
          )}
        />
      </button>

      {/* Expanded project nav */}
      <div
        className={clsx(
          'overflow-hidden transition-all duration-250 ease-out',
          isExpanded ? 'max-h-[500px] opacity-100' : 'max-h-0 opacity-0',
        )}
      >
        <div className="pl-4 pr-2 pb-2 space-y-0.5">
          {projectNavItems.map((item) => {
            const isItemActive = isActive && activeTab === item.id
            const href = getProjectNavHref(project.id, item)

            return (
              <ProjectNavItem
                key={item.id}
                item={item}
                href={href}
                isActive={isItemActive}
              />
            )
          })}

          {/* Settings link */}
          <Link
            href={`/projects/${project.id}/settings`}
            className={clsx(
              'group flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200',
              isActive && pathname.includes('/settings')
                ? 'bg-slate-500/15 text-slate-300'
                : 'text-slate-400 hover:bg-slate-500/10 hover:text-slate-300',
            )}
          >
            <Settings2
              className={clsx(
                'w-4 h-4 flex-shrink-0 transition-colors duration-200',
                isActive && pathname.includes('/settings')
                  ? 'text-slate-300'
                  : 'text-slate-500 group-hover:text-slate-300',
              )}
            />
            <span className="truncate">Settings</span>
          </Link>
        </div>
      </div>
    </div>
  )
}
