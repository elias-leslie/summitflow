import { describe, expect, it } from 'vitest'
import { throwFromResponse } from './utils'

describe('throwFromResponse', () => {
  it('surfaces the canonical API message', async () => {
    const response = new Response(
      JSON.stringify({
        error: 'http_error',
        message: 'Failed to start autonomous execution',
      }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    )

    await expect(throwFromResponse(response, 'Request failed')).rejects.toThrow(
      'Failed to start autonomous execution',
    )
  })

  it('keeps legacy detail support', async () => {
    const response = new Response(
      JSON.stringify({ detail: 'legacy failure' }),
      {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      },
    )

    await expect(throwFromResponse(response, 'Request failed')).rejects.toThrow(
      'legacy failure',
    )
  })

  it('reads a nested detail message', async () => {
    const response = new Response(
      JSON.stringify({ detail: { message: 'nested failure' } }),
      { status: 422, headers: { 'Content-Type': 'application/json' } },
    )

    await expect(throwFromResponse(response, 'Request failed')).rejects.toThrow(
      'nested failure',
    )
  })
})
