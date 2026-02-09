import clsx from 'clsx'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useGitHealth } from '@/hooks/useGitHealth'
import { GitStatusIndicator } from './GitStatusIndicator'
import { navItems } from './constants'

export function Navigation() {
  const pathname = usePathname()
  const gitHealth = useGitHealth()

  return (
    <nav className="hidden lg:flex items-center gap-1 ml-4">
      {navItems.map((item) => {
        const Icon = item.icon
        const isActive =
          pathname === item.href ||
          (item.href !== '/' && pathname.startsWith(item.href))

        return (
          <Link
            key={item.id}
            href={item.href}
            className={clsx(
              'group flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200',
              isActive
                ? item.activeColor === 'outrun'
                  ? 'bg-outrun-500/15 text-outrun-400'
                  : item.activeColor === 'violet'
                    ? 'bg-violet-500/15 text-violet-400'
                    : 'bg-indigo-500/15 text-indigo-400'
                : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-300',
            )}
          >
            <Icon
              className={clsx(
                'w-4 h-4 transition-colors duration-200',
                isActive
                  ? item.activeColor === 'outrun'
                    ? 'text-outrun-400'
                    : item.activeColor === 'violet'
                      ? 'text-violet-400'
                      : 'text-indigo-400'
                  : 'text-slate-500 group-hover:text-slate-400',
              )}
            />
            <span>{item.label}</span>
            {item.id === 'git' && <GitStatusIndicator state={gitHealth} />}
          </Link>
        )
      })}
    </nav>
  )
}
