import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Runtime Management | SummitFlow',
  description:
    'Manage native services, Docker-backed infra, and Proxmox status for the SummitFlow ecosystem',
}

export default function RuntimeLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
