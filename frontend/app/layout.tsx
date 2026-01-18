import type { Metadata } from 'next'
import './globals.css'
import { AppShell } from '@/components/layout/AppShell'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'
import { VoiceOverlayWrapper } from '@/components/VoiceOverlayWrapper'
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
            <VoiceOverlayWrapper />
          </div>
        </Providers>
      </body>
    </html>
  )
}
