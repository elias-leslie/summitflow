import { Suspense } from 'react'
import { JohnnyChatClient } from './JohnnyChatClient'

export const metadata = {
  title: 'Chat with Johnny — SummitFlow',
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="flex-1 flex items-center justify-center text-muted-foreground">Loading...</div>}>
      <JohnnyChatClient />
    </Suspense>
  )
}
