const fs = require('fs')
const path = require('path')
const os = require('os')

const CONFIG_FILE = path.join(os.homedir(), '.cloudflare-access')

function parseList(value) {
  return (value || '').split(',').map((item) => item.trim()).filter(Boolean)
}

const CLOUDFLARE_DOMAINS = parseList(process.env.CF_ACCESS_DOMAINS)
const WEBSOCKET_DOMAINS = parseList(process.env.CF_ACCESS_WEBSOCKET_DOMAINS)

let cachedCredentials = null

function loadCredentials() {
  if (cachedCredentials !== null) return cachedCredentials

  const envClientId = process.env.CF_ACCESS_CLIENT_ID
  const envClientSecret = process.env.CF_ACCESS_CLIENT_SECRET
  if (envClientId && envClientSecret) {
    cachedCredentials = { clientId: envClientId, clientSecret: envClientSecret }
    return cachedCredentials
  }

  if (!fs.existsSync(CONFIG_FILE)) {
    cachedCredentials = null
    return null
  }

  try {
    const config = {}
    for (const line of fs.readFileSync(CONFIG_FILE, 'utf8').split('\n')) {
      const trimmed = line.trim()
      if (!trimmed || trimmed.startsWith('#')) continue
      const [key, ...valueParts] = trimmed.split('=')
      config[key.trim()] = valueParts.join('=').trim()
    }

    if (config.CF_ACCESS_CLIENT_ID && config.CF_ACCESS_CLIENT_SECRET) {
      cachedCredentials = {
        clientId: config.CF_ACCESS_CLIENT_ID,
        clientSecret: config.CF_ACCESS_CLIENT_SECRET,
      }
      return cachedCredentials
    }
  } catch (error) {
    console.error(`Warning: Failed to read ${CONFIG_FILE}: ${error.message}`)
  }

  cachedCredentials = null
  return null
}

function matchesConfiguredDomain(url, domains) {
  try {
    const { hostname } = new URL(url)
    return domains.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`))
  } catch {
    return false
  }
}

function isCloudflareUrl(url) {
  return matchesConfiguredDomain(url, CLOUDFLARE_DOMAINS)
}

function hasCloudflareCredentials() {
  return loadCredentials() !== null
}

function headersForUrl(url) {
  if (!isCloudflareUrl(url)) return {}
  const credentials = loadCredentials()
  if (!credentials) return {}
  return {
    'CF-Access-Client-Id': credentials.clientId,
    'CF-Access-Client-Secret': credentials.clientSecret,
  }
}

function shouldAttachWebSocketHeaders(url) {
  return matchesConfiguredDomain(url, WEBSOCKET_DOMAINS)
}

module.exports = {
  hasCloudflareCredentials,
  headersForUrl,
  isCloudflareUrl,
  shouldAttachWebSocketHeaders,
}
