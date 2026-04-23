import { attachReviewOverlay } from '@summitflow/review-overlay'
import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ReviewOverlayReferenceHost,
  type ReviewOverlayReferenceRequest,
} from '@/components/design/live-review/ReviewOverlayReferenceHost'

function makeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('review overlay package reference host', () => {
  beforeEach(() => {
    document.body.innerHTML =
      '<div id="page-target" data-testid="hero">Hero</div>'
    window.history.replaceState(
      {},
      '',
      '/projects/summitflow/design/?tab=grid#anchor',
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('reuses the same overlay instance for a repeated overlayId and destroy removes the host', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(makeJsonResponse([])))
    vi.stubGlobal('fetch', fetchMock)

    const first = attachReviewOverlay({
      projectId: 'summitflow',
      summitflowBaseUrl: 'http://localhost:8001',
      agentHubEmbedUrl: 'http://localhost:3003/embed?projectId=summitflow',
      getAuthHeaders: () => ({}),
      overlayId: 'review-overlay-test',
    })
    const second = attachReviewOverlay({
      projectId: 'summitflow',
      summitflowBaseUrl: 'http://localhost:8001',
      agentHubEmbedUrl: 'http://localhost:3003/embed?projectId=summitflow',
      getAuthHeaders: () => ({}),
      overlayId: 'review-overlay-test',
    })

    expect(second).toBe(first)
    expect(
      document.querySelectorAll(
        '[data-review-overlay-host="review-overlay-test"]',
      ),
    ).toHaveLength(1)

    first.destroy()

    await waitFor(() => {
      expect(
        document.querySelector(
          '[data-review-overlay-host="review-overlay-test"]',
        ),
      ).toBeNull()
    })
  })

  it('captures a pin click, saves evidence, and refreshes the recent evidence list with a normalized page key', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(makeJsonResponse([]))
      .mockResolvedValueOnce(
        makeJsonResponse(
          {
            evidence_id: 'evidence-1234abcd',
            project_id: 'summitflow',
            page_key: '/projects/summitflow/design',
            page_url_snapshot:
              'http://localhost:3001/projects/summitflow/design/?tab=grid#anchor',
            comment: 'Pin this spacing issue.',
            selector: '[data-testid="hero"]',
            anchor: {
              coordinate_space: 'document_css_px',
              x: 10,
              y: 20,
              scroll_x: 0,
              scroll_y: 0,
              viewport_width: 1280,
              viewport_height: 720,
            },
            created_by_kind: 'user',
            created_by_display: 'Elias',
            created_at: '2026-04-23T01:00:00+00:00',
          },
          201,
        ),
      )
      .mockResolvedValueOnce(
        makeJsonResponse([
          {
            evidence_id: 'evidence-1234abcd',
            project_id: 'summitflow',
            page_key: '/projects/summitflow/design',
            page_url_snapshot:
              'http://localhost:3001/projects/summitflow/design/?tab=grid#anchor',
            comment: 'Pin this spacing issue.',
            selector: '[data-testid="hero"]',
            anchor: {
              coordinate_space: 'document_css_px',
              x: 10,
              y: 20,
              scroll_x: 0,
              scroll_y: 0,
              viewport_width: 1280,
              viewport_height: 720,
            },
            created_by_kind: 'user',
            created_by_display: 'Elias',
            created_at: '2026-04-23T01:00:00+00:00',
          },
        ]),
      )
    vi.stubGlobal('fetch', fetchMock)

    const handle = attachReviewOverlay({
      projectId: 'summitflow',
      summitflowBaseUrl: 'http://localhost:8001',
      agentHubEmbedUrl: 'http://localhost:3003/embed?projectId=summitflow',
      getAuthHeaders: () => ({ Authorization: 'Bearer test-token' }),
      overlayId: 'review-overlay-flow',
    })

    const host = document.querySelector(
      '[data-review-overlay-host="review-overlay-flow"]',
    ) as HTMLElement
    const shadowRoot = host.shadowRoot as ShadowRoot
    const pinButton = shadowRoot.querySelector(
      '[data-testid="review-overlay-pin-button"]',
    ) as HTMLButtonElement
    pinButton.click()

    const pageTarget = document.querySelector('#page-target') as HTMLElement
    pageTarget.getBoundingClientRect = () =>
      ({
        x: 10,
        y: 20,
        left: 10,
        top: 20,
        width: 100,
        height: 40,
        right: 110,
        bottom: 60,
        toJSON: () => ({}),
      }) as DOMRect
    pageTarget.dispatchEvent(
      new MouseEvent('click', {
        bubbles: true,
        cancelable: true,
        clientX: 24,
        clientY: 48,
      }),
    )

    const commentInput = shadowRoot.querySelector(
      '[data-testid="review-overlay-comment-input"]',
    ) as HTMLTextAreaElement
    commentInput.value = 'Pin this spacing issue.'
    commentInput.dispatchEvent(new Event('input', { bubbles: true }))

    const submitButton = shadowRoot.querySelector(
      '[data-testid="review-overlay-submit-button"]',
    ) as HTMLButtonElement
    submitButton.click()

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(3)
    })

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'http://localhost:8001/api/projects/summitflow/route-evidence?page_key=%2Fprojects%2Fsummitflow%2Fdesign&limit=10',
    )

    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      'http://localhost:8001/api/projects/summitflow/route-evidence',
    )
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: 'POST' })
    expect(fetchMock.mock.calls[1]?.[1]?.headers).toMatchObject({
      Authorization: 'Bearer test-token',
      'Content-Type': 'application/json',
    })
    expect(
      JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body)),
    ).toMatchObject({
      page_key: '/projects/summitflow/design',
      comment: 'Pin this spacing issue.',
      selector: '[data-testid="hero"]',
    })

    await waitFor(() => {
      expect(shadowRoot.textContent).toContain('Pin this spacing issue.')
    })

    handle.destroy()
  })

  it('shows an auth warning but still mounts the embedded chat when list/save returns 401', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(makeJsonResponse({ detail: 'Unauthorized' }, 401)),
      )
    vi.stubGlobal('fetch', fetchMock)

    attachReviewOverlay({
      projectId: 'summitflow',
      summitflowBaseUrl: 'http://localhost:8001',
      agentHubEmbedUrl: 'http://localhost:3003/embed?projectId=summitflow',
      getAuthHeaders: () => ({ Authorization: 'Bearer expired' }),
      overlayId: 'review-overlay-auth',
    })

    const host = document.querySelector(
      '[data-review-overlay-host="review-overlay-auth"]',
    ) as HTMLElement
    const shadowRoot = host.shadowRoot as ShadowRoot

    await waitFor(() => {
      expect(shadowRoot.textContent).toContain('Authentication required')
    })
    expect(shadowRoot.querySelector('iframe')).not.toBeNull()
  })

  it('reference host mounts the reusable overlay for an active request and cleans up on unmount', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(makeJsonResponse([])))
    vi.stubGlobal('fetch', fetchMock)

    const request: ReviewOverlayReferenceRequest = {
      projectId: 'summitflow',
      summitflowBaseUrl: 'http://localhost:8001',
      agentHubEmbedUrl: 'http://localhost:3003/embed?projectId=summitflow',
      overlayId: 'summitflow-design-overlay',
      pageKey: '/projects/summitflow/design',
      pageUrlSnapshot: 'http://localhost:3001/projects/summitflow/design',
      title: 'Design workspace review',
    }

    const { unmount } = render(
      <ReviewOverlayReferenceHost
        request={request}
        getAuthHeaders={() => ({})}
      />,
    )

    await waitFor(() => {
      expect(
        document.querySelector(
          '[data-review-overlay-host="summitflow-design-overlay"]',
        ),
      ).not.toBeNull()
    })

    unmount()

    await waitFor(() => {
      expect(
        document.querySelector(
          '[data-review-overlay-host="summitflow-design-overlay"]',
        ),
      ).toBeNull()
    })
  })
})
