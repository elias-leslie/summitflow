#!/usr/bin/env node
import process from 'node:process'
import readline from 'node:readline/promises'
import { stdin as input, stdout as output } from 'node:process'
import { claimPairing, revokePairing } from './api'
import { launchDedicatedBrowser } from './browser'
import { buildEgressSummary, parseArgs } from './core'
import { startConnectorServer } from './server'
import type { ConnectorSessionConfig } from './types'

async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2))
  const claim = options.dryRun
    ? null
    : await claimPairing({
        apiBaseUrl: options.apiBaseUrl,
        pairingId: options.pairingId,
        pairingToken: options.pairingToken,
        profileLabel: options.profileLabel,
      })
  const targetUrl = options.targetUrl ?? claim?.session.target_url ?? 'about:blank'
  const session: ConnectorSessionConfig = {
    apiBaseUrl: options.apiBaseUrl,
    sessionId: claim?.session.session_id ?? 'dry-run-session',
    pairingId: options.pairingId,
    connectorToken: claim?.connector_token ?? 'dry-run-token-not-served',
    sensitiveMode: claim?.session.sensitive ?? true,
  }
  const egress = buildEgressSummary(options.apiBaseUrl, targetUrl, options.port)
  try {
    await confirmEgress(egress.allowedOrigins, options.yes || options.dryRun)
  } catch (error) {
    if (!options.dryRun) {
      await revokePairing(session)
    }
    throw error
  }

  const server = options.dryRun
    ? null
    : await startConnectorServer({
        preferredPort: options.port,
        session,
        egress,
      })
  const launch = launchDedicatedBrowser({
    browserPath: options.browserPath,
    profileDir: options.profileDir,
    extensionDir: options.extensionDir,
    targetUrl,
    dryRun: options.dryRun,
  })

  output.write(
    `${JSON.stringify(
      {
        ok: true,
        session_id: session.sessionId,
        pairing_id: session.pairingId,
        target_url: targetUrl,
        sensitive_mode: session.sensitiveMode,
        profile_dir: options.profileDir,
        extension_dir: options.extensionDir,
        browser_path: launch.browserPath,
        browser_pid: launch.pid,
        local_connector_url: server?.url ?? null,
        revoke_url: server ? `${server.url}/revoke` : null,
        egress,
      },
      null,
      2,
    )}\n`,
  )

  if (server) {
    process.on('SIGINT', () => {
      void server.close().finally(() => process.exit(0))
    })
  }
}

async function confirmEgress(origins: string[], accepted: boolean): Promise<void> {
  output.write(`Reviewable egress:\n${origins.map((origin) => `- ${origin}`).join('\n')}\n`)
  if (accepted) return
  if (!process.stdin.isTTY) {
    throw new Error('Pass --yes after reviewing egress origins')
  }
  const rl = readline.createInterface({ input, output })
  const answer = await rl.question('Proceed? [y/N] ')
  rl.close()
  if (!/^y(es)?$/i.test(answer.trim())) {
    throw new Error('Cancelled')
  }
}

main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`)
  process.exitCode = 1
})
