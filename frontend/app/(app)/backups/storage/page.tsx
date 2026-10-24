import { redirect } from 'next/navigation'

// Storage is viewed and edited on the Backups page.
export default function Page() {
  redirect('/backups')
}
