import os from 'node:os'
import path from 'node:path'
import type { ConnectorOptions, EgressSummary } from './types'

export const CONNECTOR_VERSION = '0.1.0'
export const DEFAULT_PORT = 47618

export function parseArgs(argv: string[]): ConnectorOptions {
  const values = new Map<string, string | boolean>()
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (!arg.startsWith('--')) {
      throw new Error(`Unexpected argument: ${arg}`)
    }
    const key = arg.slice(2)
    if (key === 'yes' || key === 'dry-run') {
      values.set(key, true)
      continue
    }
    const next = argv[index + 1]
    if (!next || next.startsWith('--')) {
      throw new Error(`Missing value for --${key}`)
    }
    values.set(key, next)
    index += 1
  }

  const apiBaseUrl = stringValue(values, 'api') ?? process.env.SUMMITFLOW_API_URL ?? 'http://127.0.0.1:8001/api'
  const pairingId = stringValue(values, 'pairing-id') ?? process.env.SUMMITFLOW_PAIRING_ID
  const pairingToken = stringValue(values, 'pairing-token') ?? process.env.SUMMITFLOW_PAIRING_TOKEN
  if (!pairingId && !values.get('dry-run')) throw new Error('--pairing-id is required')
  if (!pairingToken && !values.get('dry-run')) throw new Error('--pairing-token is required')

  return {
    apiBaseUrl: normalizeApiBaseUrl(apiBaseUrl),
    pairingId: pairingId ?? 'pairing-dryrun',
    pairingToken: pairingToken ?? 'dryrun-token-not-used',
    browserPath: stringValue(values, 'browser'),
    extensionDir: path.resolve(stringValue(values, 'extension-dir') ?? defaultExtensionDir()),
    profileDir: path.resolve(stringValue(values, 'profile-dir') ?? defaultProfileDir()),
    profileLabel: stringValue(values, 'profile-label') ?? 'SummitFlow Review',
    targetUrl: stringValue(values, 'target-url'),
    yes: Boolean(values.get('yes')),
    dryRun: Boolean(values.get('dry-run')),
    port: numberValue(values, 'port') ?? DEFAULT_PORT,
  }
}

export function normalizeApiBaseUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, '')
  if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://')) {
    throw new Error('API URL must start with http:// or https://')
  }
  return trimmed.endsWith('/api') ? trimmed : `${trimmed}/api`
}

export function buildEgressSummary(apiBaseUrl: string, targetUrl: string | null, port: number): EgressSummary {
  const apiOrigin = new URL(apiBaseUrl).origin
  const targetOrigin = targetUrl && targetUrl !== 'about:blank' ? new URL(targetUrl).origin : null
  const localOrigin = `http://127.0.0.1:${port}`
  return {
    apiOrigin,
    targetOrigin,
    localOrigin,
    allowedOrigins: [apiOrigin, localOrigin, ...(targetOrigin ? [targetOrigin] : [])],
  }
}

export function buildBrowserArgs(options: {
  profileDir: string
  extensionDir: string
  targetUrl: string
}): string[] {
  return [
    `--user-data-dir=${options.profileDir}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-sync',
    '--disable-extensions-file-access-check',
    '--disable-features=AutofillServerCommunication,PasswordManagerOnboarding',
    `--load-extension=${options.extensionDir}`,
    options.targetUrl,
  ]
}

export function resolveBrowserCandidates(explicit?: string): string[] {
  if (explicit) return [explicit]
  if (process.platform === 'win32') {
    return [
      path.join(process.env.PROGRAMFILES ?? 'C:\\Program Files', 'Google\\Chrome\\Application\\chrome.exe'),
      path.join(process.env['PROGRAMFILES(X86)'] ?? 'C:\\Program Files (x86)', 'Google\\Chrome\\Application\\chrome.exe'),
      path.join(process.env.LOCALAPPDATA ?? '', 'Google\\Chrome\\Application\\chrome.exe'),
      path.join(process.env.PROGRAMFILES ?? 'C:\\Program Files', 'Microsoft\\Edge\\Application\\msedge.exe'),
      path.join(process.env['PROGRAMFILES(X86)'] ?? 'C:\\Program Files (x86)', 'Microsoft\\Edge\\Application\\msedge.exe'),
    ].filter(Boolean)
  }
  return ['google-chrome', 'chromium', 'chromium-browser', 'microsoft-edge']
}

function defaultProfileDir(): string {
  const base = process.env.LOCALAPPDATA || path.join(os.homedir(), '.summitflow')
  return path.join(base, 'SummitFlow', 'CoBrowserProfile')
}

function defaultExtensionDir(): string {
  return path.resolve(import.meta.dirname, '..', '..', 'summitflow-chromium-extension')
}

function stringValue(values: Map<string, string | boolean>, key: string): string | undefined {
  const value = values.get(key)
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function numberValue(values: Map<string, string | boolean>, key: string): number | undefined {
  const raw = stringValue(values, key)
  if (!raw) return undefined
  const value = Number(raw)
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`Invalid --${key}`)
  }
  return value
}
