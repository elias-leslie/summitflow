import type { NextConfig } from 'next'
import { PORTS } from './lib/api-config'

const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  transpilePackages: ['@agent-hub/chat-ui', '@agent-hub/push-client'],
  allowedDevOrigins: [
    'dev.summitflow.dev',
    '*.summitflow.dev',
    '192.168.8.244',
  ],
  // API routing via Next.js rewrites for CF Access compatibility
  // Browser requests /api/* and /ws/* -> Next.js rewrites -> localhost backend
  // This enables same-origin routing, avoiding CF Access cookie issues
  async rewrites() {
    const apiUrl = process.env.API_URL || `http://localhost:${PORTS.backend}`
    const agentHubApiUrl = process.env.AGENT_HUB_URL || `http://localhost:${PORTS.agentHub}`
    return {
      // Agent Hub proxy: Route Handler at app/proxy-hub/agent-hub/[...path]/route.ts
      // injects client credentials and streams SSE directly to Agent Hub.
      // beforeFiles intercepts /api/agent-hub/* BEFORE the /api/* catch-all can grab it.
      beforeFiles: [
        {
          source: '/api/agent-hub/:path*',
          destination: '/proxy-hub/agent-hub/:path*',
        },
        // Voice STT/TTS: proxy to Agent Hub backend (not SummitFlow)
        // Must be in beforeFiles so /api/:path* catch-all doesn't grab it
        {
          source: '/api/voice/:path*',
          destination: `${agentHubApiUrl}/api/voice/:path*`,
        },
      ],
      afterFiles: [
        // All other API calls proxy to SummitFlow backend
        {
          source: '/api/:path*',
          destination: `${apiUrl}/api/:path*`,
        },
        // WebSocket paths - same-origin routing for CF Access compatibility
        {
          source: '/ws/:path*',
          destination: `${apiUrl}/ws/:path*`,
        },
      ],
      fallback: [],
    }
  },
}

export default nextConfig
