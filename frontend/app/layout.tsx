import type { Metadata, Viewport } from 'next'
import Script from 'next/script'
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

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#ffffff' },
    { media: '(prefers-color-scheme: dark)', color: '#0f172a' },
  ],
  width: 'device-width',
  initialScale: 1,
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="manifest" href="/manifest.json" />
        <link rel="apple-touch-icon" href="/icons/icon-192.png" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="SummitFlow" />
      </head>
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
        <Script
          id="sw-register"
          strategy="afterInteractive"
          dangerouslySetInnerHTML={{
            __html: `
              if ('serviceWorker' in navigator) {
                window.addEventListener('load', function() {
                  navigator.serviceWorker.register('/sw.js').then(
                    function(registration) {
                      console.log('SW registered:', registration.scope);
                    },
                    function(err) {
                      console.log('SW registration failed:', err);
                    }
                  );
                });
              }
            `,
          }}
        />
      </body>
    </html>
  )
}
