import clsx from 'clsx'
import { ExternalLink } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useGitHealth } from '@/hooks/useGitHealth'
import { navItems } from './constants'
import { GitStatusIndicator } from './GitStatusIndicator'

interface NavigationProps {
  compact?: boolean
  dense?: boolean
  measure?: boolean
}

export function Navigation({
  compact = false,
  dense = false,
  measure = false,
}: NavigationProps) {
  const pathname = usePathname()
  const gitHealth = useGitHealth()
  const labelClassName = compact ? 'hidden' : 'inline'
  const externalIconClassName = compact || dense ? 'hidden' : 'block'

  return (
    <nav
      className={clsx(
        'flex min-w-0 items-center transition-all duration-300',
        measure ? 'w-max gap-1 whitespace-nowrap' : 'w-full overflow-hidden',
        dense ? 'justify-start gap-1' : 'justify-center gap-1.5',
      )}
    >
      {navItems.map((item) => {
        const Icon = item.icon
        const isExternal = 'external' in item && item.external
        const isActive =
          !isExternal &&
          (pathname === item.href ||
            (item.href !== '/' && pathname.startsWith(item.href)))

        const activeStyles: Record<string, { bg: string; text: string }> = {
          outrun: { bg: 'bg-outrun-500/15', text: 'text-outrun-400' },
          violet: { bg: 'bg-violet-500/15', text: 'text-violet-400' },
          phosphor: { bg: 'bg-phosphor-500/15', text: 'text-phosphor-400' },
          rose: { bg: 'bg-rose-500/15', text: 'text-rose-400' },
          indigo: { bg: 'bg-indigo-500/15', text: 'text-indigo-400' },
          cyan: { bg: 'bg-cyan-500/15', text: 'text-cyan-400' },
          fuchsia: { bg: 'bg-fuchsia-500/15', text: 'text-fuchsia-400' },
        }
        const ac = activeStyles[item.activeColor] ?? activeStyles.indigo

        const label = item.label

        const className = clsx(
          'group relative flex shrink-0 items-center gap-2 whitespace-nowrap rounded-full font-medium transition-all duration-200',
          dense ? 'gap-1 text-[11px]' : 'text-[13px]',
          compact
            ? 'p-2'
            : dense
              ? 'px-2.5 py-1.5'
              : 'px-3 py-1.5 lg:px-3.5 lg:py-2',
          isActive
            ? `${ac.bg} ${ac.text} shadow-[0_18px_38px_-30px_rgba(0,0,0,0.95)] ring-1 ring-white/5`
            : 'text-slate-400 hover:bg-slate-800/72 hover:text-slate-200',
        )

        const iconClassName = clsx(
          'w-4 h-4 transition-colors duration-200',
          isActive ? ac.text : 'text-slate-500 group-hover:text-slate-300',
        )

        const content = (
          <>
            <Icon className={iconClassName} />
            <span className={labelClassName}>{label}</span>
            {item.id === 'git' && <GitStatusIndicator state={gitHealth} />}
            {isExternal && (
              <ExternalLink
                className={clsx(
                  'h-3 w-3 text-slate-600 group-hover:text-slate-500',
                  externalIconClassName,
                )}
              />
            )}
            {isActive && (
              <span
                className="absolute inset-x-3 bottom-1 h-px rounded-full bg-current opacity-65"
                style={{ boxShadow: '0 0 12px currentColor' }}
                aria-hidden="true"
              />
            )}
          </>
        )

        if (isExternal) {
          return (
            <a
              key={item.id}
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
              className={className}
              title={label}
            >
              {content}
            </a>
          )
        }

        return (
          <Link
            key={item.id}
            href={item.href}
            className={className}
            title={label}
          >
            {content}
          </Link>
        )
      })}
    </nav>
  )
}
