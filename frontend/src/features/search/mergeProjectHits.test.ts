import { describe, expect, it } from 'vitest'
import { mergeProjectHits } from './SearchPage'

describe('mergeProjectHits', () => {
  it('merges projects, removes duplicate ranges, and keeps score order', () => {
    const hit = (video_id: string, score: number) => ({
      video_id, source_start_ms: 1000, source_end_ms: 6000, score,
    })
    expect(mergeProjectHits([
      [hit('video-a', 0.6), hit('shared-video', 0.7)],
      [hit('video-b', 0.9), hit('shared-video', 0.8)],
    ])).toEqual([hit('video-b', 0.9), hit('shared-video', 0.8), hit('video-a', 0.6)])
  })
})
