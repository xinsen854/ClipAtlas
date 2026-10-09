import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountFineCut } from '../src/index'

const PLAN_ID = '11111111-1111-1111-1111-111111111111'
const CONTEXT_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const CONTEXT_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
const CLIP_A = '44444444-4444-4444-4444-444444444441'
const CLIP_B = '44444444-4444-4444-4444-444444444442'
const SEGMENT_A = '77777777-7777-7777-7777-777777777771'
const SEGMENT_B = '77777777-7777-7777-7777-777777777772'
const MEDIA_A = '66666666-6666-6666-6666-666666666661'
const MEDIA_B = '66666666-6666-6666-6666-666666666662'

const timeline = {
  version: 1,
  project_id: '22222222-2222-2222-2222-222222222222',
  source_plan_id: PLAN_ID,
  width: 1920,
  height: 1080,
  fps: 30,
  duration_ms: 10000,
  tracks: [{
    id: '33333333-3333-3333-3333-333333333333',
    kind: 'video',
    clips: [
      {
        id: CLIP_A,
        source_id: SEGMENT_A,
        source_path: 'D:/media/a.mp4',
        timeline_start_ms: 1000,
        duration_ms: 2000,
        source_in_ms: 10000,
        source_out_ms: 12000,
        opacity: 1,
        volume: 1,
        transform: {},
        effects: [],
      },
      {
        id: CLIP_B,
        source_id: SEGMENT_B,
        source_path: 'D:/media/b.mp4',
        timeline_start_ms: 3000,
        duration_ms: 2000,
        source_in_ms: 20000,
        source_out_ms: 22000,
        opacity: 1,
        volume: 1,
        transform: {},
        effects: [],
      },
    ],
  }],
}

const narration = {
  track_id: '55555555-5555-5555-5555-555555555555',
  revision: 2,
  audio_uri: 'D:/audio/narration.wav',
  duration_ms: 10000,
  segments: [
    { id: CONTEXT_A, text: '句子 A', start_ms: 0, end_ms: 3000 },
    { id: CONTEXT_B, text: '句子 B', start_ms: 3000, end_ms: 6000 },
  ],
}

function candidate(contextId: string, mediaId: string) {
  return {
    requirement_id: `${contextId}-candidate`, sentence_id: contextId, source_quote: contextId,
    importance: 'S', candidate_type: 'window', candidate_id: null, media_id: mediaId,
    source_in_ms: 0, source_out_ms: 4000, anchor_in_ms: null, anchor_out_ms: null,
    continuity_status: 'confirmed_continuity', display_level: 'S', pollution_level: 'clean',
    visual_family: 'family', presentation_type: 'wide', subject_score: 1, action_score: 1,
    scene_score: 1, environment_score: 1, object_score: 1, configuration_score: 1,
    quantity_score: 1, relation_score: 1, order_score: 1, vector_score: 1,
    preliminary_level: 'strong_candidate',
  }
}

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function installFetch(options: {
  unresolved?: Set<string>
  resolverMap?: Record<string, string>
} = {}) {
  const resolverMap = options.resolverMap ?? { [SEGMENT_A]: MEDIA_A, [SEGMENT_B]: MEDIA_B }
  const unresolved = options.unresolved ?? new Set<string>()
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/timeline`)) return response(timeline)
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/narration`)) return response(narration)
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_A}`)) {
      return response({ context_id: CONTEXT_A, items: [candidate(CONTEXT_A, MEDIA_A)] })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_B}`)) {
      return response({ context_id: CONTEXT_B, items: [candidate(CONTEXT_B, MEDIA_B)] })
    }
    const match = url.match(new RegExp(`/finecut/plans/${PLAN_ID}/media-resolution/([^/?#]+)$`))
    if (match) {
      const sourceId = decodeURIComponent(match[1])
      if (unresolved.has(sourceId) || !resolverMap[sourceId]) return response({ detail: 'media unresolved' }, 404)
      const mediaId = resolverMap[sourceId]
      return response({ media_id: mediaId, source_uri: `D:/media/${mediaId}.mp4` })
    }
    return new Response('not found', { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function mountWorkspace(options: Parameters<typeof installFetch>[0] = {}) {
  const fetchMock = installFetch(options)
  const root = document.createElement('div')
  document.body.append(root)
  const dispose = mountFineCut(root, { planId: PLAN_ID })
  await vi.waitFor(() => expect(root.textContent).toContain('句子 A'))
  return { root, dispose, fetchMock }
}

function previewVideo(root: HTMLElement): HTMLVideoElement {
  const video = root.querySelector<HTMLVideoElement>('[data-finecut-preview-video]')
  expect(video).not.toBeNull()
  if (!video) throw new Error('preview video missing')
  return video
}

function setMediaState(video: HTMLVideoElement, values: { currentTime?: number; paused?: boolean }) {
  if (values.currentTime !== undefined) {
    Object.defineProperty(video, 'currentTime', { configurable: true, writable: true, value: values.currentTime })
  }
  if (values.paused !== undefined) {
    Object.defineProperty(video, 'paused', { configurable: true, value: values.paused })
  }
}

function mockPlayback(video: HTMLVideoElement) {
  const play = vi.fn(async () => undefined)
  const pause = vi.fn()
  Object.defineProperty(video, 'play', { configurable: true, value: play })
  Object.defineProperty(video, 'pause', { configurable: true, value: pause })
  return { play, pause }
}

function dispatchTimeUpdate(video: HTMLVideoElement, seconds: number) {
  setMediaState(video, { currentTime: seconds })
  video.dispatchEvent(new Event('timeupdate'))
}

function seekRange(root: HTMLElement, ms: number) {
  const range = root.querySelector<HTMLInputElement>('input[type="range"]')
  expect(range).not.toBeNull()
  if (!range) return
  range.value = String(ms)
  range.dispatchEvent(new Event('input', { bubbles: true }))
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.replaceChildren()
})

describe('FineCut Phase 4B V1 preview player', () => {
  it('P1 resolves the active clip and uses existing source-media with muted video', async () => {
    const { root, dispose, fetchMock } = await mountWorkspace()
    seekRange(root, 1500)

    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const video = previewVideo(root)
    expect(video.muted).toBe(true)
    expect(video.getAttribute('src')).toContain(`/api/v1/videos/${MEDIA_A}/source-media`)
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith(
      `/finecut/plans/${PLAN_ID}/media-resolution/${SEGMENT_A}`,
    ))).toBe(true)
    dispose()
  })

  it('P2 maps timeline seek to source_in plus offset', async () => {
    const { root, dispose } = await mountWorkspace()
    seekRange(root, 1750)
    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const video = previewVideo(root)
    video.dispatchEvent(new Event('loadedmetadata'))
    expect(video.currentTime).toBeCloseTo(10.75, 3)
    dispose()
  })

  it('P3 maps video timeupdate back to the single timeline playhead without full workspace rerender', async () => {
    const { root, dispose } = await mountWorkspace()
    seekRange(root, 1500)
    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const video = previewVideo(root)
    dispatchTimeUpdate(video, 11.25)

    expect(root.querySelector('[data-finecut-preview-video]')).toBe(video)
    expect(root.querySelector<HTMLInputElement>('input[type="range"]')?.value).toBe('2250')
    expect(root.textContent).toContain('预览位置 0:02.3')
    dispose()
  })

  it('P4 play and pause control the active V1 video without a second timeline clock', async () => {
    const { root, dispose } = await mountWorkspace()
    seekRange(root, 1500)
    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const video = previewVideo(root)
    const playback = mockPlayback(video)

    root.querySelector<HTMLButtonElement>('[aria-label="播放预览"]')?.click()
    expect(playback.play).toHaveBeenCalledTimes(1)
    root.querySelector<HTMLButtonElement>('[aria-label="暂停预览"]')?.click()
    expect(playback.pause).toHaveBeenCalled()
    dispose()
  })

  it('P5 never seeks before source_in when entering a clip', async () => {
    const { root, dispose } = await mountWorkspace()
    seekRange(root, 1000)
    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const video = previewVideo(root)
    video.dispatchEvent(new Event('loadedmetadata'))
    expect(video.currentTime).toBe(10)
    dispose()
  })

  it('P6 clamps at source_out and does not continue into unused source media', async () => {
    const { root, dispose } = await mountWorkspace({ unresolved: new Set([SEGMENT_B]) })
    seekRange(root, 1500)
    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const video = previewVideo(root)
    const playback = mockPlayback(video)
    dispatchTimeUpdate(video, 12)

    expect(playback.pause).toHaveBeenCalled()
    expect(root.querySelector<HTMLInputElement>('input[type="range"]')?.value).toBe('3000')
    await vi.waitFor(() => expect(root.textContent).toContain('无法解析'))
    dispose()
  })

  it('P7 switches to the adjacent clip source and continues playback', async () => {
    const { root, dispose } = await mountWorkspace()
    seekRange(root, 1500)
    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const firstVideo = previewVideo(root)
    mockPlayback(firstVideo)
    setMediaState(firstVideo, { paused: false })
    dispatchTimeUpdate(firstVideo, 12)

    await vi.waitFor(() => {
      const next = previewVideo(root)
      expect(next).not.toBe(firstVideo)
      expect(next.getAttribute('src')).toContain(`/api/v1/videos/${MEDIA_B}/source-media`)
    })
    const next = previewVideo(root)
    const playback = mockPlayback(next)
    next.dispatchEvent(new Event('loadedmetadata'))
    expect(next.currentTime).toBe(20)
    expect(playback.play).toHaveBeenCalled()
    dispose()
  })

  it('P8 pauses at a real timeline gap and does not jump to the nearest clip', async () => {
    const gapTimeline = structuredClone(timeline)
    gapTimeline.tracks[0].clips[1].timeline_start_ms = 4000
    const fetchMock = installFetch()
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith(`/finecut/plans/${PLAN_ID}/timeline`)) return response(gapTimeline)
      if (url.endsWith(`/finecut/plans/${PLAN_ID}/narration`)) return response(narration)
      const match = url.match(new RegExp(`/finecut/plans/${PLAN_ID}/media-resolution/([^/?#]+)$`))
      if (match) {
        const sourceId = decodeURIComponent(match[1])
        const mediaId = sourceId === SEGMENT_A ? MEDIA_A : MEDIA_B
        return response({ media_id: mediaId, source_uri: `D:/media/${mediaId}.mp4` })
      }
      if (url.includes('/candidates/')) return response({ context_id: CONTEXT_A, items: [] })
      return new Response('not found', { status: 404 })
    })
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })
    await vi.waitFor(() => expect(root.textContent).toContain('句子 A'))
    seekRange(root, 1500)
    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const video = previewVideo(root)
    const playback = mockPlayback(video)
    dispatchTimeUpdate(video, 12)

    expect(playback.pause).toHaveBeenCalled()
    expect(root.querySelector<HTMLInputElement>('input[type="range"]')?.value).toBe('3000')
    expect(root.textContent?.toLowerCase()).toContain('gap')
    dispose()
  })

  it('P9 shows a safe unavailable state for unresolved media without guessing source_path', async () => {
    const { root, dispose } = await mountWorkspace({ unresolved: new Set([SEGMENT_A]) })
    seekRange(root, 1500)

    await vi.waitFor(() => expect(root.textContent).toContain('无法解析'))
    expect(root.querySelector('[data-finecut-preview-video]')).toBeNull()
    const preview = root.querySelector<HTMLElement>('.finecut-preview')
    expect(preview).not.toBeNull()
    expect(preview?.innerHTML).not.toContain('D:/media/a.mp4')
    dispose()
  })

  it('P10 handles HTML video playback errors without changing timeline data', async () => {
    const { root, dispose } = await mountWorkspace()
    seekRange(root, 1500)
    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const video = previewVideo(root)
    const playback = mockPlayback(video)
    video.dispatchEvent(new Event('error'))

    expect(playback.pause).toHaveBeenCalled()
    expect(root.textContent).toContain('无法播放')
    expect(root.querySelector(`[data-clip-id="${CLIP_A}"]`)).not.toBeNull()
    dispose()
  })

  it('P11 seeking into a gap stops video and shows gap state', async () => {
    const { root, dispose } = await mountWorkspace()
    seekRange(root, 7000)

    await vi.waitFor(() => expect(root.textContent?.toLowerCase()).toContain('gap'))
    expect(root.querySelector('[data-finecut-preview-video]')).toBeNull()
    expect(root.querySelector<HTMLInputElement>('input[type="range"]')?.value).toBe('7000')
    dispose()
  })

  it('P12 uses half-open boundaries so an exact shared edge activates the next clip', async () => {
    const { root, dispose, fetchMock } = await mountWorkspace()
    seekRange(root, 3000)

    await vi.waitFor(() => expect(previewVideo(root).getAttribute('src')).toContain(`/api/v1/videos/${MEDIA_B}/source-media`))
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith(
      `/finecut/plans/${PLAN_ID}/media-resolution/${SEGMENT_B}`,
    ))).toBe(true)
    dispose()
  })

  it('P13 continuous manual seek inside one active clip does not recreate the video element', async () => {
    const { root, dispose } = await mountWorkspace()
    seekRange(root, 1200)
    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const video = previewVideo(root)

    seekRange(root, 1400)
    seekRange(root, 1600)
    seekRange(root, 1800)

    expect(root.querySelector('[data-finecut-preview-video]')).toBe(video)
    expect(root.querySelector<HTMLInputElement>('input[type="range"]')?.value).toBe('1800')
    dispose()
  })
})
