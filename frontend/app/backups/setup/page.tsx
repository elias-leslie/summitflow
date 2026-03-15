import { StorageSetupWizard } from '@/components/backup/StorageSetupWizard'

export default function BackupSetupPage() {
  return (
    <main className="content-container py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-100">Backup Setup</h1>
        <p className="text-sm text-slate-400 mt-1">
          Configure where your backups are stored
        </p>
      </div>
      <StorageSetupWizard />
    </main>
  )
}
