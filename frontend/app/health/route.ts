/** Lightweight frontend reachability probe for SummitFlow project health checks. */
export function GET(): Response {
  return Response.json(
    { status: 'healthy', service: 'summitflow-frontend' },
    { headers: { 'Cache-Control': 'no-store' } },
  )
}
