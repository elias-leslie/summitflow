import Script from 'next/script'
import { AppShell } from '@/components/layout/AppShell'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'
import { Providers } from '../providers'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
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
    </Providers>
  )
}
