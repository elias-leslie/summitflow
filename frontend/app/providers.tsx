'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { Toaster } from 'sonner'
import { POLL_SLOW } from '@/lib/polling'

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: POLL_SLOW,
            refetchOnWindowFocus: false,
          },
        },
      }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: '#150d20',
            border: '1px solid #2d1d42',
            color: '#e4e7eb',
            boxShadow: '0 8px 24px -4px rgba(0,0,0,0.5), 0 0 0 1px rgba(45,29,66,0.3)',
          },
          className: 'sonner-toast',
        }}
      />
    </QueryClientProvider>
  )
}
