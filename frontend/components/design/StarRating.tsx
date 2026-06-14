'use client'

import clsx from 'clsx'
import { Star } from 'lucide-react'

interface StarRatingProps {
  average: number
  count: number
  userRating: number
  disabled?: boolean
  compact?: boolean
  onRate: (rating: number) => void
}

export function StarRating({
  average,
  count,
  userRating,
  disabled = false,
  compact = false,
  onRate,
}: StarRatingProps): React.ReactElement {
  const roundedAverage = Number.isFinite(average) ? average : 0
  const displayAverage = roundedAverage.toFixed(1)

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div
        className="flex items-center gap-1"
        aria-label={`Average rating ${displayAverage} out of 5`}
      >
        {[1, 2, 3, 4, 5].map((rating) => {
          const selected = userRating >= rating
          return (
            <button
              key={rating}
              type="button"
              aria-label={
                userRating === rating
                  ? `Clear ${rating} star rating`
                  : `Rate ${rating} star${rating === 1 ? '' : 's'}`
              }
              title={
                userRating === rating
                  ? `Clear ${rating} star rating`
                  : `Rate ${rating} star${rating === 1 ? '' : 's'}`
              }
              disabled={disabled}
              onClick={(event) => {
                event.preventDefault()
                event.stopPropagation()
                onRate(userRating === rating ? 0 : rating)
              }}
              onKeyDown={(event) => event.stopPropagation()}
              className={clsx(
                'rounded p-0.5 transition disabled:cursor-not-allowed disabled:opacity-60',
                selected
                  ? 'text-amber-300'
                  : 'text-slate-600 hover:text-amber-200',
              )}
            >
              <Star
                className={compact ? 'h-4 w-4' : 'h-5 w-5'}
                fill={selected ? 'currentColor' : 'none'}
              />
            </button>
          )
        })}
      </div>
      <span
        className={
          compact ? 'text-xs text-slate-400' : 'text-sm text-slate-300'
        }
      >
        {displayAverage} · {count} {count === 1 ? 'rating' : 'ratings'}
      </span>
    </div>
  )
}
