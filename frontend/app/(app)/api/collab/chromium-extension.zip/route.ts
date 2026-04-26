import { PORTS } from '@/lib/api-config'

function backendUrl(): string {
  const base = process.env.API_URL ?? `http://localhost:${PORTS.backend}`
  return `${base.replace(/\/+$/, '')}/api/collab/chromium-extension.zip`
}

export async function GET() {
  const upstream = await fetch(backendUrl(), { cache: 'no-store' })
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'Content-Type':
        upstream.headers.get('content-type') ?? 'application/octet-stream',
      'Content-Disposition':
        upstream.headers.get('content-disposition') ??
        'attachment; filename="summitflow-cobrowser-extension.zip"',
      'Cache-Control': 'no-store',
    },
  })
}
