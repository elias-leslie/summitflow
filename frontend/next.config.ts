import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@agent-hub/passport-client'],
  // API routing is handled client-side via lib/api-config.ts
  // No rewrites needed - getWsUrl() and buildApiUrl() resolve to correct backend URL
  // based on window.location (localhost for dev, devapi.summitflow.dev for prod)
}

export default nextConfig
