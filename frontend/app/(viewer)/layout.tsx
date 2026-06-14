import { Providers } from '../providers'

export default function ViewerLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <Providers>
      <div className="flex h-screen flex-col overflow-hidden bg-grid">
        {children}
      </div>
    </Providers>
  )
}
