import type { Metadata, Viewport } from 'next'
import {
  Outfit,
  Bricolage_Grotesque,
  JetBrains_Mono,
  Fira_Code,
  IBM_Plex_Mono,
} from 'next/font/google'
import Script from 'next/script'
import './globals.css'
import { AppShell } from '@/components/layout/AppShell'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'
import { Providers } from './providers'

// Primary body font — warm geometric sans
const outfit = Outfit({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-body',
  display: 'swap',
})

// Display font for headings — editorial, angular, characterful
const bricolageGrotesque = Bricolage_Grotesque({
  subsets: ['latin'],
  weight: ['500', '600', '700', '800'],
  variable: '--font-display',
  display: 'swap',
})

// Primary mono font
const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-mono',
  display: 'swap',
})

// Alternative mono fonts
const firaCode = Fira_Code({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-fira-code',
  display: 'swap',
})

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-ibm-plex-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'SummitFlow',
  description: 'AI-assisted software development platform',
}

export const viewport: Viewport = {
  themeColor: '#0a0612',
  width: 'device-width',
  initialScale: 1,
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html
      lang="en"
      className={`dark ${outfit.variable} ${bricolageGrotesque.variable} ${jetbrainsMono.variable} ${firaCode.variable} ${ibmPlexMono.variable}`}
    >
      <head>
        <link
          rel="icon"
          type="image/png"
          sizes="192x192"
          href="/icons/icon-192.png?v=20"
        />
        <link rel="manifest" href="/manifest.json?v=20" />
        <link rel="apple-touch-icon" href="/icons/icon-192.png?v=20" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta
          name="apple-mobile-web-app-status-bar-style"
          content="black-translucent"
        />
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
          </div>
        </Providers>
        <Script
          id="sw-register"
          strategy="afterInteractive"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: Static service worker registration code
          dangerouslySetInnerHTML={{
            __html: `
              if ('serviceWorker' in navigator) {
                window.addEventListener('load', function() {
                  navigator.serviceWorker.register('/sw.js?v=23').catch(function(e) { if (process.env.NODE_ENV === 'development') console.warn('SW registration failed:', e); });
                });
              }
            `,
          }}
        />
      </body>
    </html>
  )
}
