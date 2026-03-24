import { StorageSetupWizard } from '@/components/backup/StorageSetupWizard'

export default function BackupSetupPage() {
  return (
    <main className="content-container py-8">
      <div className="mb-8 hero-glow">
        <h1 className="text-2xl font-bold text-slate-100 display tracking-tight relative z-10">Backup Setup</h1>
        <p className="text-sm text-slate-400 mt-1">
          Configure where your backups are stored
        </p>
      </div>
      <StorageSetupWizard />
    </main>
  )
}
