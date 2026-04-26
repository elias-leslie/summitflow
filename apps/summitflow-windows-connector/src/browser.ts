import fs from 'node:fs'
import { spawn } from 'node:child_process'
import { buildBrowserArgs, resolveBrowserCandidates } from './core'

export interface BrowserLaunchResult {
  browserPath: string
  args: string[]
  pid: number | null
}

export function launchDedicatedBrowser(options: {
  browserPath?: string
  profileDir: string
  extensionDir: string
  targetUrl: string
  dryRun: boolean
}): BrowserLaunchResult {
  fs.mkdirSync(options.profileDir, { recursive: true })
  const browserPath = resolveBrowserPath(options.browserPath)
  const args = buildBrowserArgs({
    profileDir: options.profileDir,
    extensionDir: options.extensionDir,
    targetUrl: options.targetUrl,
  })
  if (options.dryRun) {
    return { browserPath, args, pid: null }
  }
  const child = spawn(browserPath, args, {
    detached: true,
    stdio: 'ignore',
    windowsHide: false,
  })
  child.unref()
  return { browserPath, args, pid: child.pid ?? null }
}

function resolveBrowserPath(explicit?: string): string {
  for (const candidate of resolveBrowserCandidates(explicit)) {
    if (candidate.includes('/') || candidate.includes('\\')) {
      if (fs.existsSync(candidate)) return candidate
      continue
    }
    return candidate
  }
  throw new Error('Could not find Chrome, Chromium, or Edge. Pass --browser.')
}
