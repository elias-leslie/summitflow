import { afterEach, describe, expect, it, vi } from 'vitest'
import { backupDriveFolderUrl, cancelBackup } from './backups'

describe('backupDriveFolderUrl', () => {
  it('opens the source folder containing the archive or complete parts set', () => {
    expect(
      backupDriveFolderUrl(
        'google-drive://owner@example.com/root-id/backup-root/source_folder-1/archive-id',
      ),
    ).toBe('https://drive.google.com/drive/folders/source_folder-1')
    expect(
      backupDriveFolderUrl(
        'google-drive://owner@example.com/root-id/backup-root/source_folder-1/manifest-id',
      ),
    ).toBe('https://drive.google.com/drive/folders/source_folder-1')
  })

  it.each([
    null,
    '',
    'not a URL',
    'https://other.example/root/folder/file',
    'google-drive://owner@example.com/root-id/folder-id',
    'google-drive://owner@example.com/root-id/folder-id/archive.tar.gz.age',
    'google-drive://owner@example.com/root-id/folder-id/file-id?share=yes',
    'google-drive://owner@example.com/root-id/folder-id/file-id#fragment',
    'google-drive://owner@example.com/root-id/folder%2fid/file-id',
    'google-drive://owner@example.com/root-id/folder-id/file-id/',
  ])(
    'does not invent a link for ambiguous or unsupported metadata: %s',
    (location) => {
      expect(backupDriveFolderUrl(location)).toBeNull()
    },
  )
})

describe('cancelBackup', () => {
  afterEach(() => vi.restoreAllMocks())

  it('binds cancellation to the exact observed run and encodes resource IDs', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          task_id: 'run-1',
          status: 'cancelling',
          message: 'Cancellation requested',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    await expect(
      cancelBackup('source/name', 'backup/name', 'run-1'),
    ).resolves.toMatchObject({ status: 'cancelling' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toContain(
      '/api/backup-sources/source%2Fname/backups/backup%2Fname/cancel',
    )
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ run_id: 'run-1' }),
    })
  })

  it('does not retry a rejected stale cancellation against a newer run', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          error: 'http_error',
          message: 'Backup run changed',
          details: [],
        }),
        { status: 409, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    await expect(cancelBackup('source', 'backup', 'old-run')).rejects.toThrow(
      'Backup run changed',
    )
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
