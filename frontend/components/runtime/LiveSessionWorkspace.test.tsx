import { describe, expect, it } from 'vitest'
import { mapLiveFramePoint } from './LiveSessionWorkspace'

describe('mapLiveFramePoint', () => {
  it('maps operator clicks against the rendered frame image rect', () => {
    const point = mapLiveFramePoint(
      730,
      410,
      { left: 10, top: 50, width: 960, height: 540 },
      1920,
      1080,
    )

    expect(point).toEqual({ x: 1440, y: 720 })
  })

  it('ignores clicks outside the rendered frame image', () => {
    const point = mapLiveFramePoint(
      20,
      20,
      { left: 10, top: 50, width: 960, height: 540 },
      1920,
      1080,
    )

    expect(point).toBeNull()
  })
})
