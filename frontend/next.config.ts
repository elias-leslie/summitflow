import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@agent-hub/passport-client'],
  // API routing via Next.js rewrites for CF Access compatibility
  // See: ~/.claude/rules.archive/cloudflare-access.md
  // Browser requests /api/* -> Next.js rewrites -> localhost:8001/api/*
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8001/api/:path*',
      },
    ]
  },
}

export default nextConfig
