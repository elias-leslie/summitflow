'use client'

import Image from 'next/image'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { useIsLg } from '@/hooks/useMediaQuery'
import {
  LOGO_CONTAINER_WIDTH,
  LOGO_HEIGHT,
  LOGO_SHIFT_COLLAPSED,
  LOGO_SQUARE_SIZE,
  LOGO_WIDE_WIDTH,
} from './constants'

export function AnimatedLogo() {
  const router = useRouter()
  const [isExpanded, setIsExpanded] = useState(false)
  const collapseTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const isLg = useIsLg()

  useEffect(() => {
    if (isExpanded) {
      collapseTimeoutRef.current = setTimeout(() => {
        setIsExpanded(false)
      }, 3500)
    }

    return () => {
      if (collapseTimeoutRef.current) {
        clearTimeout(collapseTimeoutRef.current)
      }
    }
  }, [isExpanded])

  const handleLogoClick = () => {
    router.push('/')
    if (!isExpanded && isLg) {
      setIsExpanded(true)
    }
  }

  // Below lg: compact icon-only logo
  const compact = !isLg

  return (
    <button
      type="button"
      onClick={handleLogoClick}
      className="flex items-center flex-shrink-0 group focus:outline-none"
      aria-label="Go to dashboard"
      style={{
        width: compact ? LOGO_SQUARE_SIZE : LOGO_CONTAINER_WIDTH,
        height: LOGO_HEIGHT,
        transition: 'width 0.3s ease-out',
      }}
    >
      <div
        className="flex items-center"
        style={{
          justifyContent: isExpanded ? 'center' : 'flex-start',
          width: '100%',
          transition: 'justify-content 0.3s ease-out',
        }}
      >
        <div
          className="relative flex-shrink-0 overflow-hidden"
          style={{
            width: isExpanded ? LOGO_WIDE_WIDTH : LOGO_SQUARE_SIZE,
            height: LOGO_HEIGHT,
            transition: 'width 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
          }}
        >
          <Image
            src="/logo-wide-v4.svg"
            alt="SummitFlow"
            width={LOGO_WIDE_WIDTH}
            height={LOGO_HEIGHT}
            className="h-full"
            style={{
              width: LOGO_WIDE_WIDTH,
              minWidth: LOGO_WIDE_WIDTH,
              transform: isExpanded
                ? 'translateX(0)'
                : `translateX(-${LOGO_SHIFT_COLLAPSED}px)`,
              transition: 'transform 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
              filter: isExpanded
                ? 'drop-shadow(0 0 20px rgba(255,102,0,0.4)) drop-shadow(0 0 40px rgba(255,0,102,0.2))'
                : 'drop-shadow(0 0 12px rgba(255,102,0,0.3)) drop-shadow(0 0 24px rgba(255,0,102,0.15))',
            }}
            priority
          />
        </div>

        {!compact && (
          <div
            className="overflow-hidden flex-shrink-0"
            style={{
              maxWidth: isExpanded ? 0 : 140,
              marginLeft: isExpanded ? 0 : 12,
              transition:
                'max-width 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94), margin-left 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
            }}
          >
            <span
              className="font-semibold text-xl tracking-tight whitespace-nowrap block"
              style={{
                background:
                  'linear-gradient(90deg, #fff200 0%, #ff6600 50%, #ff0066 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
                transform: isExpanded ? 'translateX(-20px)' : 'translateX(0)',
                transition:
                  'transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
              }}
            >
              SummitFlow
            </span>
          </div>
        )}
      </div>

      <div
        className="absolute inset-0 pointer-events-none rounded-lg opacity-0 group-hover:opacity-100"
        style={{
          boxShadow:
            '0 0 30px rgba(255,102,0,0.08), 0 0 60px rgba(255,0,102,0.05)',
          transition: 'opacity 0.3s ease-out',
        }}
      />
    </button>
  )
}
