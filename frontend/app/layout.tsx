import type { Metadata, Viewport } from 'next'
import {
  Outfit,
  Bricolage_Grotesque,
  JetBrains_Mono,
} from 'next/font/google'
import clsx from 'clsx'
import './globals.css'

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
      className={clsx('dark', outfit.variable, bricolageGrotesque.variable, jetbrainsMono.variable)}
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
        {children}
      </body>
    </html>
  )
}
