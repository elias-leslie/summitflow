import http from 'node:http'
import type { AddressInfo } from 'node:net'
import type { ConnectorSessionConfig, EgressSummary } from './types'
import { revokePairing } from './api'

export interface ConnectorServer {
  port: number
  url: string
  close: () => Promise<void>
}

export async function startConnectorServer(options: {
  preferredPort: number
  session: ConnectorSessionConfig
  egress: EgressSummary
}): Promise<ConnectorServer> {
  let extensionSessionAvailable = true
  const server = http.createServer((request, response) => {
    const origin = request.headers.origin
    if (origin?.startsWith('chrome-extension://')) {
      response.setHeader('access-control-allow-origin', origin)
      response.setHeader('access-control-allow-headers', 'content-type')
      response.setHeader('access-control-allow-methods', 'GET,POST,OPTIONS')
    }
    if (request.method === 'OPTIONS') {
      response.writeHead(204)
      response.end()
      return
    }

    const url = new URL(request.url ?? '/', `http://127.0.0.1:${options.preferredPort}`)
    if (request.method === 'GET' && url.pathname === '/health') {
      writeJson(response, 200, { ok: true, session_id: options.session.sessionId })
      return
    }
    if (request.method === 'GET' && url.pathname === '/egress') {
      writeJson(response, 200, options.egress)
      return
    }
    if (request.method === 'GET' && url.pathname === '/extension-session') {
      if (!origin?.startsWith('chrome-extension://')) {
        writeJson(response, 403, { error: 'extension origin required' })
        return
      }
      if (!extensionSessionAvailable) {
        writeJson(response, 410, { error: 'extension session already claimed' })
        return
      }
      extensionSessionAvailable = false
      writeJson(response, 200, options.session)
      return
    }
    if (request.method === 'POST' && url.pathname === '/revoke') {
      void revokePairing(options.session).finally(() => {
        extensionSessionAvailable = false
        writeJson(response, 200, { ok: true, revoked: true })
      })
      return
    }
    writeJson(response, 404, { error: 'not found' })
  })

  const port = await listen(server, options.preferredPort)
  return {
    port,
    url: `http://127.0.0.1:${port}`,
    close: () =>
      new Promise((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()))
      }),
  }
}

async function listen(server: http.Server, preferredPort: number): Promise<number> {
  for (let port = preferredPort; port < preferredPort + 11; port += 1) {
    try {
      await new Promise<void>((resolve, reject) => {
        server.once('error', reject)
        server.listen(port, '127.0.0.1', () => {
          server.off('error', reject)
          resolve()
        })
      })
      const address = server.address() as AddressInfo
      return address.port
    } catch {
      continue
    }
  }
  throw new Error('No local connector port available')
}

function writeJson(response: http.ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { 'content-type': 'application/json' })
  response.end(JSON.stringify(body))
}
