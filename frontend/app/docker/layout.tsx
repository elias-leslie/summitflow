import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Runtime Management | SummitFlow',
  description:
    'Manage native services and Docker-backed infra for the SummitFlow ecosystem',
}

export default function DockerLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
