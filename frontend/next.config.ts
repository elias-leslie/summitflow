import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@agent-hub/chat-ui'],
  // API routing via Next.js rewrites for CF Access compatibility
  // Browser requests /api/* and /ws/* -> Next.js rewrites -> localhost:8001
  // This enables same-origin routing, avoiding CF Access cookie issues
  async rewrites() {
    return {
      // Agent Hub proxy: Route Handler at app/proxy-hub/agent-hub/[...path]/route.ts
      // injects client credentials and streams SSE directly to Agent Hub (localhost:8003).
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
          destination: 'http://localhost:8003/api/voice/:path*',
        },
      ],
      afterFiles: [
        // All other API calls proxy to SummitFlow backend
        {
          source: '/api/:path*',
          destination: 'http://localhost:8001/api/:path*',
        },
        // WebSocket paths - same-origin routing for CF Access compatibility
        {
          source: '/ws/:path*',
          destination: 'http://localhost:8001/ws/:path*',
        },
      ],
      fallback: [],
    }
  },
}

export default nextConfig
