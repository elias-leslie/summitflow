import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Docker Management | SummitFlow',
  description: 'Manage Docker containers for the SummitFlow ecosystem',
}

export default function DockerLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
