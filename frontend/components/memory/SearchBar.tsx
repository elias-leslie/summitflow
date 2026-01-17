'use client'

import { clsx } from 'clsx'
import { Loader2, Search } from 'lucide-react'
import { type KeyboardEvent, useState } from 'react'

interface SearchBarProps {
  onSearch: (query: string) => void
  isLoading?: boolean
  placeholder?: string
}

export function SearchBar({
  onSearch,
  isLoading = false,
  placeholder = 'Search observations, patterns, diary...',
}: SearchBarProps) {
  const [query, setQuery] = useState('')

  const handleSearch = () => {
    if (query.trim()) {
      onSearch(query.trim())
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }

  return (
    <div className="flex items-center gap-2 w-full max-w-2xl">
      <div className="relative flex-1">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isLoading}
          className={clsx(
            'w-full px-4 py-2.5 pl-10 rounded-lg',
            'bg-slate-800/50 border border-slate-700/50',
            'text-slate-200 placeholder-slate-500',
            'focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            'transition-all duration-200',
          )}
        />
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
      </div>
      <button
        onClick={handleSearch}
        disabled={isLoading || !query.trim()}
        className={clsx(
          'px-4 py-2.5 rounded-lg font-medium',
          'bg-blue-600 hover:bg-blue-500 text-white',
          'disabled:bg-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed',
          'transition-colors duration-200',
          'flex items-center gap-2',
        )}
      >
        {isLoading ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Search className="w-4 h-4" />
        )}
        Search
      </button>
    </div>
  )
}
