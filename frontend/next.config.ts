import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@agent-hub/passport-client', '@agent-hub/chat-ui'],
  // API routing via Next.js rewrites for CF Access compatibility
  // Browser requests /api/* and /ws/* -> Next.js rewrites -> localhost:8001
  // This enables same-origin routing, avoiding CF Access cookie issues
  async rewrites() {
    return [
      // Agent Hub requests go through /api/agent-hub/* which is proxied
      // to localhost:8001 (SummitFlow backend) along with all other /api/* calls.
      // The backend then forwards to Agent Hub with proper client credentials.
      {
        source: '/api/:path*',
        destination: 'http://localhost:8001/api/:path*',
      },
      // WebSocket paths - same-origin routing for CF Access compatibility
      {
        source: '/ws/:path*',
        destination: 'http://localhost:8001/ws/:path*',
      },
    ]
  },
}

export default nextConfig
