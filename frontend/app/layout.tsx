import type { Metadata } from 'next'
import './globals.css'
import { VoiceOverlay } from '@agent-hub/passport-client'
import { AppShell } from '@/components/layout/AppShell'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'
import { Providers } from './providers'

export const metadata: Metadata = {
  title: 'SummitFlow',
  description: 'AI-assisted software development platform',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">
        <Providers>
          <div className="flex flex-col h-screen overflow-hidden">
            {/* Top navigation bar */}
            <TopBar />

            {/* Main content area with sidebar */}
            <AppShell>
              <div className="flex flex-1 overflow-hidden">
                {/* Sidebar - shows on all pages, adapts to context */}
                <Sidebar />

                {/* Main content */}
                <main className="flex-1 overflow-auto bg-grid">{children}</main>
              </div>
            </AppShell>
            <VoiceOverlay wsUrl="wss://agentapi.summitflow.dev/api/voice/ws?user_id=summitflow_user&app=summitflow" />
          </div>
        </Providers>
      </body>
    </html>
  )
}
