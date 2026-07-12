import clsx from 'clsx'
import { ChevronDown, GripVertical, Settings2 } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ButtonHTMLAttributes } from 'react'
import type { Project } from '@/lib/api'
import { projectNavItems } from './constants'
import { ProjectNavItem } from './ProjectNavItem'
import type { NavItemId } from './types'
import { useProjectPermissionTier } from './useProjectPermissionTier'

const TIER_BADGE_CONFIG = {
  off: {
    label: 'OFF',
    bg: 'bg-slate-600/30',
    text: 'text-slate-500',
    border: 'border-slate-600/40',
  },
  read: {
    label: 'R',
    bg: 'bg-blue-500/15',
    text: 'text-blue-400',
    border: 'border-blue-500/30',
  },
  full: {
    label: 'F',
    bg: 'bg-emerald-500/15',
    text: 'text-emerald-400',
    border: 'border-emerald-500/30',
  },
} as const

interface ProjectAccordionItemProps {
  project: Project
  isExpanded: boolean
  isActive: boolean
  activeTab: NavItemId | null
  onToggleExpand: () => void
  getProjectNavHref: (
    projectId: string,
    item: (typeof projectNavItems)[number],
  ) => string
  dragHandleProps?: ButtonHTMLAttributes<HTMLButtonElement>
  isDragging?: boolean
}

export function ProjectAccordionItem({
  project,
  isExpanded,
  isActive,
  activeTab,
  onToggleExpand,
  getProjectNavHref,
  dragHandleProps,
  isDragging = false,
}: ProjectAccordionItemProps) {
  const pathname = usePathname()
  const tier = useProjectPermissionTier(project.id)
  const badge = tier
    ? TIER_BADGE_CONFIG[tier as keyof typeof TIER_BADGE_CONFIG]
    : null
  const healthLabel = project.health_status === 'healthy' ? 'healthy' : 'watch'

  return (
    <div
      className={clsx(
        'group/project-item relative overflow-hidden rounded-[1.35rem] border transition-all duration-200',
        isDragging && 'opacity-75',
        isActive
          ? 'border-outrun-500/24 bg-gradient-to-br from-outrun-500/12 via-transparent to-violet-500/8 shadow-[0_24px_60px_-46px_rgba(255,0,102,0.9)]'
          : 'border-slate-800/70 bg-slate-900/52 hover:border-slate-700/65 hover:bg-slate-900/76',
      )}
      data-testid="project-accordion-item"
      data-expanded={isExpanded}
    >
      {dragHandleProps ? (
        <button
          type="button"
          aria-label={`Reorder ${project.name}`}
          title={`Reorder ${project.name}`}
          {...dragHandleProps}
          className={clsx(
            'pointer-events-none absolute left-1.5 top-1/2 z-10 flex h-7 w-5 -translate-y-1/2 items-center justify-center rounded-full border border-slate-800/70 bg-slate-950/85 text-slate-500 opacity-0 shadow-lg shadow-black/25 transition-all duration-150',
            'group-hover/project-item:pointer-events-auto group-hover/project-item:opacity-100',
            'group-focus-within/project-item:pointer-events-auto group-focus-within/project-item:opacity-100',
            'hover:border-slate-700/70 hover:text-slate-300',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outrun-500/40',
            isDragging && 'pointer-events-auto opacity-100',
          )}
        >
          <GripVertical className="h-3.5 w-3.5" />
        </button>
      ) : null}

      {/* Project header */}
      <div
        className={clsx(
          'flex items-stretch gap-2 px-3 py-2.5',
          isActive ? 'bg-transparent' : 'hover:bg-slate-800/30',
        )}
      >
        <Link
          href={`/projects/${project.id}`}
          data-testid={`project-link-${project.id}`}
          className="group/project-link flex min-w-0 flex-1 items-start gap-2.5 rounded-[1rem] text-left transition-all duration-200"
        >
          {/* Project icon with health indicator */}
          <div className="relative mt-0.5 flex-shrink-0">
            <div
              className={clsx(
                'flex h-8 w-8 items-center justify-center rounded-xl border transition-all duration-200',
                isActive
                  ? 'border-outrun-500/28 bg-gradient-to-br from-outrun-500/22 to-violet-500/14'
                  : 'border-slate-700/60 bg-slate-800/60 group-hover/project-link:border-slate-600/80',
              )}
            >
              <span
                className={clsx(
                  'text-sm font-bold transition-colors',
                  isActive
                    ? 'text-outrun-400'
                    : 'text-slate-400 group-hover/project-link:text-slate-300',
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
          <div className="min-w-0 flex-1 text-left">
            <div
              className={clsx(
                'break-words text-sm font-semibold leading-5 whitespace-normal transition-colors',
                isActive
                  ? 'text-slate-100'
                  : 'text-slate-300 group-hover/project-link:text-slate-100',
              )}
            >
              {project.name}
            </div>
            <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-500">
              <span className="truncate font-mono">{project.id}</span>
              <span className="rounded-full border border-slate-700/60 bg-slate-900/60 px-1.5 py-0.5 uppercase tracking-[0.16em] text-[9px] text-slate-400">
                {healthLabel}
              </span>
            </div>
          </div>

          {/* Permission tier badge */}
          {badge && (
            <span
              className={clsx(
                'mt-0.5 flex-shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-bold leading-none',
                badge.bg,
                badge.text,
                badge.border,
              )}
              title={`Permission tier: ${tier}`}
            >
              {badge.label}
            </span>
          )}
        </Link>

        <button
          type="button"
          onClick={onToggleExpand}
          data-testid={`project-accordion-toggle-${project.id}`}
          aria-expanded={isExpanded}
          aria-label={`Toggle ${project.name} navigation`}
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl border border-slate-800/70 bg-slate-950/50 text-slate-500 transition-colors hover:border-slate-700/70 hover:bg-slate-900/80 hover:text-slate-300"
        >
          <ChevronDown
            className={clsx(
              'h-4 w-4 transition-all duration-250',
              isExpanded && 'rotate-180 text-outrun-400',
            )}
          />
        </button>
      </div>

      {/* Keep collapsed links out of the accessibility tree and tab order. */}
      {isExpanded ? (
        <div className="animate-in overflow-hidden">
          <div className="mx-3 mb-3 rounded-2xl border border-slate-800/70 bg-slate-950/40 p-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]">
            <div className="space-y-1">
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
                  'group flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200',
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
      ) : null}
    </div>
  )
}
