'use client'

import clsx from 'clsx'
import { Bell, BellOff, BellRing } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  getPermissionState,
  isPushSupported,
  isSubscribed,
  subscribe,
  unsubscribe,
} from '@agent-hub/push-client'
import { FEEDBACK_TIMEOUT, PUSH_NOTIFICATION_TIMEOUT } from '@/lib/polling'

type PushState = 'loading' | 'unsupported' | 'denied' | 'subscribed' | 'unsubscribed'

export function PushNotificationToggle() {
  const [state, setState] = useState<PushState>('loading')

  useEffect(() => {
    async function check() {
      if (!isPushSupported()) {
        setState('unsupported')
        return
      }
      if (getPermissionState() === 'denied') {
        setState('denied')
        return
      }
      try {
        const subscribed = await isSubscribed()
        setState(subscribed ? 'subscribed' : 'unsubscribed')
      } catch {
        // SW not ready or pushManager unavailable - show as unsubscribed
        setState('unsubscribed')
      }
    }
    // Timeout fallback in case SW ready hangs
    const timeout = setTimeout(() => setState('unsubscribed'), FEEDBACK_TIMEOUT + 1000)
    check().finally(() => clearTimeout(timeout))
  }, [])

  const handleToggle = useCallback(async () => {
    setState('loading')
    try {
      if (state === 'subscribed') {
        const ok = await Promise.race([
          unsubscribe(),
          new Promise<false>((r) => setTimeout(() => r(false), PUSH_NOTIFICATION_TIMEOUT)),
        ])
        setState(ok ? 'unsubscribed' : 'subscribed')
      } else {
        const ok = await Promise.race([
          subscribe(),
          new Promise<false>((r) => setTimeout(() => r(false), PUSH_NOTIFICATION_TIMEOUT)),
        ])
        setState(ok ? 'subscribed' : getPermissionState() === 'denied' ? 'denied' : 'unsubscribed')
      }
    } catch {
      setState('unsubscribed')
    }
  }, [state])

  if (state === 'loading') {
    return <ToggleButton icon={<Bell className="w-4 h-4 text-slate-500 animate-pulse" />} label="Loading..." disabled />
  }

  if (state === 'unsupported') {
    return <ToggleButton icon={<BellOff className="w-4 h-4 text-slate-600" />} label="Push not supported" disabled />
  }

  if (state === 'denied') {
    return <ToggleButton icon={<BellOff className="w-4 h-4 text-rose-400" />} label="Push blocked" disabled />
  }

  if (state === 'subscribed') {
    return <ToggleButton icon={<BellRing className="w-4 h-4 text-phosphor-400" />} label="Push enabled" onClick={handleToggle} active />
  }

  return <ToggleButton icon={<Bell className="w-4 h-4 text-slate-400" />} label="Enable push" onClick={handleToggle} />
}

function ToggleButton({
  icon,
  label,
  onClick,
  disabled,
  active,
}: {
  icon: React.ReactNode
  label: string
  onClick?: () => void
  disabled?: boolean
  active?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors',
        active
          ? 'bg-phosphor-500/10 text-phosphor-400 hover:bg-phosphor-500/20'
          : disabled
            ? 'text-slate-600 cursor-not-allowed'
            : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200',
      )}
      title={label}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}
