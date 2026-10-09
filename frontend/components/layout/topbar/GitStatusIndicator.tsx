import clsx from 'clsx'
import type { GitHealthState } from '@/hooks/useGitHealth'

export function GitStatusIndicator({ state }: { state: GitHealthState }) {
  if (state === 'loading' || state === 'error') return null

  const colorClasses = {
    clean: 'bg-phosphor-500 shadow-[0_0_8px_rgba(0,245,255,0.7)]',
    dirty: 'bg-slate-400',
    behind: 'bg-outrun-500 shadow-[0_0_8px_rgba(255,0,102,0.7)]',
  }

  const pulseClasses = {
    clean: '',
    dirty: '',
    behind: 'animate-pulse',
  }

  return (
    <span
      className={clsx(
        'w-2 h-2 rounded-full flex-shrink-0',
        colorClasses[state],
        pulseClasses[state],
      )}
      title={
        state === 'clean'
          ? 'No uncommitted changes against local refs'
          : state === 'dirty'
            ? 'Local work: uncommitted or unpublished changes'
            : 'Behind local remote refs; refresh remote to check'
      }
    />
  )
}
