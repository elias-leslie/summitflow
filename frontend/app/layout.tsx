import type { Metadata, Viewport } from 'next'
import './globals.css'
import './fonts.css'

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
    <html lang="en" className="dark">
      <head>
        <link
          rel="preload"
          href="/fonts/1b99372b3eaef0c8-s.p.1gsd1jahc5dg_.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
        <link
          rel="preload"
          href="/fonts/017d9bea37084d9b-s.p.41rroleoq1br7.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
        <link
          rel="preload"
          href="/fonts/051742360c26797e-s.p.1bkzbscqrt8rl.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
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
      <body className="antialiased">{children}</body>
    </html>
  )
}
