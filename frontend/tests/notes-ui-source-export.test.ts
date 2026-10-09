import { dirname, resolve } from 'node:path'
import { NotesProvider } from '@summitflow/notes-ui'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'
import { NotesProvider as sourceNotesProvider } from '../../packages/notes-ui/src/index'

describe('notes-ui source export', () => {
  it('uses the tracked source export in Vitest', () => {
    expect(NotesProvider).toBe(sourceNotesProvider)
  })

  it('resolves tracked source types with the frontend compiler configuration', () => {
    const configPath = resolve(process.cwd(), 'tsconfig.json')
    const config = ts.readConfigFile(configPath, ts.sys.readFile)
    expect(config.error).toBeUndefined()
    const { options } = ts.parseJsonConfigFileContent(config.config, ts.sys, dirname(configPath))
    const resolution = ts.resolveModuleName(
      '@summitflow/notes-ui',
      resolve(dirname(configPath), 'components/layout/TopBar.tsx'),
      options,
      ts.sys
    )
    expect(resolution.resolvedModule?.resolvedFileName).toBe(
      resolve(dirname(configPath), '../packages/notes-ui/src/index.ts')
    )
  })
})
