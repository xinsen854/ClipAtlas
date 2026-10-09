import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountFineCut } from '../src/index'

const PLAN_ID = '11111111-1111-1111-1111-111111111111'
const CONTEXT_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const CONTEXT_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
const CLIP_A = '44444444-4444-4444-4444-444444444441'
const CLIP_B = '44444444-4444-4444-4444-444444444442'
const SPLIT_RIGHT = '99999999-9999-9999-9999-999999999999'
const MEDIA_A = '66666666-6666-6666-6666-666666666661'
const MEDIA_REPLACEMENT = '66666666-6666-6666-6666-666666666662'
const MEDIA_FALLBACK = '66666666-6666-6666-6666-666666666663'

const initialTimeline = {
  version: 1,
  project_id: '22222222-2222-2222-2222-222222222222',
  source_plan_id: PLAN_ID,
  width: 1920,
  height: 1080,
  fps: 30,
  duration_ms: 12000,
  tracks: [{
    id: '33333333-3333-3333-3333-333333333333',
    kind: 'video',
    clips: [
      {
        id: CLIP_A,
        source_id: 'segment-a',
        source_path: 'D:/library/source-a.mp4',
        timeline_start_ms: 0,
        duration_ms: 5000,
        source_in_ms: 1000,
        source_out_ms: 6000,
        opacity: 1,
        volume: 1,
        transform: {},
        effects: [],
      },
      {
        id: CLIP_B,
        source_id: 'missing-source',
        source_path: 'D:/library/missing.mp4',
        timeline_start_ms: 6000,
        duration_ms: 3000,
        source_in_ms: 2000,
        source_out_ms: 5000,
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
  revision: 3,
  audio_uri: 'D:/audio/narration.wav',
  duration_ms: 12000,
  segments: [
    { id: CONTEXT_A, text: '句子 A', start_ms: 0, end_ms: 6000 },
    { id: CONTEXT_B, text: '句子 B', start_ms: 6000, end_ms: 12000 },
  ],
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function candidate(
  label: string,
  displayLevel: string,
  mediaId: string,
  sourceInMs: number,
  sourceOutMs: number,
) {
  return {
    requirement_id: `${CONTEXT_A}-${label}`,
    sentence_id: CONTEXT_A,
    source_quote: label,
    importance: 'S',
    candidate_type: 'window',
    candidate_id: null,
    media_id: mediaId,
    source_in_ms: sourceInMs,
    source_out_ms: sourceOutMs,
    anchor_in_ms: sourceInMs,
    anchor_out_ms: sourceInMs + 500,
    continuity_status: 'confirmed_continuity',
    display_level: displayLevel,
    pollution_level: 'clean',
    visual_family: 'family-a',
    presentation_type: 'wide',
    subject_score: 1,
    action_score: 0.8,
    scene_score: 0.7,
    environment_score: 0.6,
    object_score: 0.5,
    configuration_score: 0.4,
    quantity_score: 0.3,
    relation_score: 0.2,
    order_score: 0.1,
    vector_score: 0.9,
    preliminary_level: 'strong_candidate',
  }
}

const directCandidate = candidate('DIRECT', 'S', MEDIA_REPLACEMENT, 10000, 17000)
const fallbackCandidate = candidate('REUSE', 'Fallback/Reuse', MEDIA_FALLBACK, 20000, 27000)

function installFetch() {
  let savedTimeline = clone(initialTimeline)
  const requests: Array<{ url: string; method: string; body: any }> = []

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    requests.push({ url, method, body })

    if (url.endsWith(`/finecut/plans/${PLAN_ID}/timeline`) && method === 'GET') {
      return response(clone(savedTimeline))
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/timeline`) && method === 'PUT') {
      savedTimeline = clone(body)
      return response(clone(savedTimeline))
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/narration`)) return response(narration)
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_A}`)) {
      return response({
        context_id: CONTEXT_A,
        items: [
          directCandidate,
          candidate('SUPPORT', 'A', MEDIA_REPLACEMENT, 30000, 37000),
          candidate('RELATED', 'B', MEDIA_REPLACEMENT, 40000, 47000),
          candidate('GENERIC', 'Generic', MEDIA_REPLACEMENT, 50000, 57000),
          candidate('SOURCE', 'Fallback/Source', MEDIA_A, 1000, 7000),
          fallbackCandidate,
          candidate('UNKNOWN', 'UNKNOWN', MEDIA_REPLACEMENT, 60000, 67000),
          candidate('REJECT', 'REJECT', MEDIA_REPLACEMENT, 70000, 77000),
        ],
      })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_B}`)) {
      return response({ context_id: CONTEXT_B, items: [] })
    }

    if (url.endsWith(`/finecut/media/${MEDIA_A}`)) {
      return response({ media_id: MEDIA_A, source_uri: 'D:/library/source-a.mp4' })
    }
    if (url.endsWith(`/finecut/media/${MEDIA_REPLACEMENT}`)) {
      return response({ media_id: MEDIA_REPLACEMENT, source_uri: 'D:/library/replacement.mp4' })
    }
    if (url.endsWith(`/finecut/media/${MEDIA_FALLBACK}`)) {
      return response({ media_id: MEDIA_FALLBACK, source_uri: 'D:/library/reuse.mp4' })
    }

    if (url.endsWith(`/finecut/plans/${PLAN_ID}/media-resolution/segment-a`)) {
      return response({ media_id: MEDIA_A, source_uri: 'D:/library/source-a.mp4' })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/media-resolution/missing-source`)) {
      return response({ detail: 'not found' }, 404)
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/media-resolution/${MEDIA_REPLACEMENT}`)) {
      return response({ media_id: MEDIA_REPLACEMENT, source_uri: 'D:/library/replacement.mp4' })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/media-resolution/${MEDIA_FALLBACK}`)) {
      return response({ media_id: MEDIA_FALLBACK, source_uri: 'D:/library/reuse.mp4' })
    }

    if (url.endsWith('/finecut/edit/replace') && method === 'POST') {
      const document = clone(body.document)
      const clip = document.tracks[0].clips.find((item: any) => item.id === body.target_clip_id)
      if (!clip) return response({ detail: 'clip not found' }, 400)
      clip.source_id = body.candidate.media_id
      clip.source_path = body.media.source_uri
      clip.source_in_ms = body.candidate.source_in_ms
      clip.source_out_ms = body.candidate.source_in_ms + clip.duration_ms
      return response(document)
    }

    if (url.endsWith('/finecut/edit/trim') && method === 'POST') {
      const document = clone(body.document)
      const clip = document.tracks[0].clips.find((item: any) => item.id === body.target_clip_id)
      if (!clip || body.delta_ms <= 0 || body.delta_ms >= clip.duration_ms) {
        return response({ detail: 'invalid trim' }, 400)
      }
      clip.duration_ms -= body.delta_ms
      if (body.edge === 'left') {
        clip.timeline_start_ms += body.delta_ms
        clip.source_in_ms += body.delta_ms
      } else {
        clip.source_out_ms -= body.delta_ms
      }
      return response(document)
    }

    if (url.endsWith('/finecut/edit/split') && method === 'POST') {
      const document = clone(body.document)
      const clips = document.tracks[0].clips
      const index = clips.findIndex((item: any) => item.id === body.target_clip_id)
      if (index < 0) return response({ detail: 'clip not found' }, 400)
      const clip = clips[index]
      const end = clip.timeline_start_ms + clip.duration_ms
      if (!(clip.timeline_start_ms < body.split_timeline_ms && body.split_timeline_ms < end)) {
        return response({ detail: 'invalid split' }, 400)
      }
      const leftDuration = body.split_timeline_ms - clip.timeline_start_ms
      const sourceSplit = clip.source_in_ms + leftDuration
      const left = { ...clip, duration_ms: leftDuration, source_out_ms: sourceSplit }
      const right = {
        ...clip,
        id: SPLIT_RIGHT,
        timeline_start_ms: body.split_timeline_ms,
        duration_ms: end - body.split_timeline_ms,
        source_in_ms: sourceSplit,
      }
      clips.splice(index, 1, left, right)
      return response(document)
    }

    return new Response('not found', { status: 404 })
  })

  vi.stubGlobal('fetch', fetchMock)
  return {
    requests,
    getSavedTimeline: () => clone(savedTimeline),
  }
}

function editCalls(harness: ReturnType<typeof installFetch>, suffix: string) {
  return harness.requests.filter((item) => item.method === 'POST' && item.url.endsWith(suffix))
}

function putCalls(harness: ReturnType<typeof installFetch>) {
  return harness.requests.filter((item) => item.method === 'PUT')
}

function findCandidateCard(root: HTMLElement, label: string): HTMLElement {
  const card = Array.from(root.querySelectorAll<HTMLElement>('.finecut-card'))
    .find((item) => item.textContent?.includes(label))
  if (!card) throw new Error(`candidate card not found: ${label}`)
  return card
}

function clickButton(root: HTMLElement, label: string) {
  const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
    .find((item) => item.textContent === label)
  if (!button) throw new Error(`button not found: ${label}`)
  button.click()
}

function clip(root: HTMLElement, clipId = CLIP_A): HTMLElement {
  const item = root.querySelector<HTMLElement>(`[data-clip-id="${clipId}"]`)
  if (!item) throw new Error(`clip not found: ${clipId}`)
  return item
}

function seek(root: HTMLElement, value: number) {
  const input = root.querySelector<HTMLInputElement>('[aria-label="时间线定位"]')
  if (!input) throw new Error('timeline seek input not found')
  input.value = String(value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

async function mountWorkspace() {
  const harness = installFetch()
  const root = document.createElement('div')
  document.body.append(root)
  const dispose = mountFineCut(root, { planId: PLAN_ID })
  await vi.waitFor(() => expect(root.querySelector(`[data-clip-id="${CLIP_A}"]`)).not.toBeNull())
  await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
  return { harness, root, dispose }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.replaceChildren()
})

describe('FineCut Phase 5B media presentation', () => {
  it('M1/M2 derives clip label and source info without adding timeline facts', async () => {
    const { harness, root, dispose } = await mountWorkspace()

    await vi.waitFor(() => expect(clip(root).querySelector('[data-clip-label]')?.textContent).toBe('source-a.mp4'))
    expect(clip(root).querySelector('[data-clip-source]')?.textContent).toContain('segment-a')

    clickButton(root, '保存')
    await vi.waitFor(() => expect(putCalls(harness)).toHaveLength(1))
    expect(harness.getSavedTimeline()).toEqual(initialTimeline)
    expect(harness.getSavedTimeline().tracks[0].clips[0]).not.toHaveProperty('thumbnail')
    expect(harness.getSavedTimeline().tracks[0].clips[0]).not.toHaveProperty('display_label')
    expect(harness.getSavedTimeline().tracks[0].clips[0]).not.toHaveProperty('missing')
    dispose()
  })

  it('M3 preserves existing candidate/fallback display semantics without reranking', async () => {
    const { root, dispose } = await mountWorkspace()

    await vi.waitFor(() => expect(clip(root).dataset.presentationMarker).toBe('Fallback/Source'))
    expect(root.textContent).not.toContain('UNKNOWN')
    expect(root.textContent).not.toContain('REJECT')

    clip(root).click()
    findCandidateCard(root, 'DIRECT').querySelector<HTMLButtonElement>('.finecut-replace')?.click()
    await vi.waitFor(() => expect(clip(root).dataset.presentationMarker).toBe('S'))

    clickButton(root, '撤销')
    await vi.waitFor(() => expect(clip(root).dataset.presentationMarker).toBe('Fallback/Source'))

    findCandidateCard(root, 'REUSE').querySelector<HTMLButtonElement>('.finecut-replace')?.click()
    await vi.waitFor(() => expect(clip(root).dataset.presentationMarker).toBe('Fallback/Reuse'))
    dispose()
  })

  it('M4 shows missing/unresolved media as a visual-only clip state', async () => {
    const { root, dispose } = await mountWorkspace()

    await vi.waitFor(() => expect(clip(root, CLIP_B).dataset.mediaStatus).toBe('missing'))
    expect(clip(root, CLIP_B).textContent).toContain('素材不可解析')
    dispose()
  })

  it('M5 missing thumbnail falls back to the normal editable clip block', async () => {
    const { harness, root, dispose } = await mountWorkspace()

    const image = await vi.waitFor(() => {
      const node = clip(root).querySelector<HTMLImageElement>('[data-clip-thumbnail]')
      expect(node).not.toBeNull()
      return node!
    })
    image.dispatchEvent(new Event('error'))
    expect(clip(root).dataset.thumbnailMissing).toBe('true')
    expect(clip(root).querySelector('[data-clip-thumbnail]')).toBeNull()

    clip(root).click()
    const input = root.querySelector<HTMLInputElement>('[aria-label="裁剪毫秒"]')!
    input.value = '500'
    clickButton(root, '右裁')
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(1))
    dispose()
  })

  it('M6 reuses the existing cached index-thumbnail route as derived presentation', async () => {
    const { root, dispose } = await mountWorkspace()

    const image = await vi.waitFor(() => {
      const node = clip(root).querySelector<HTMLImageElement>('[data-clip-thumbnail]')
      expect(node).not.toBeNull()
      return node!
    })
    expect(image.getAttribute('src')).toBe(
      `/api/v1/videos/${MEDIA_A}/index-thumbnail?timestamp_ms=3500`,
    )
    dispose()
  })

  it('M7 zoom changes geometry while label/thumbnail remain derived from the same clip', async () => {
    const { root, dispose } = await mountWorkspace()

    await vi.waitFor(() => expect(clip(root).querySelector('[data-clip-thumbnail]')).not.toBeNull())
    const beforeWidth = Number.parseFloat(clip(root).style.width)
    const beforeSrc = clip(root).querySelector<HTMLImageElement>('[data-clip-thumbnail]')?.getAttribute('src')

    root.querySelector<HTMLButtonElement>('[aria-label="放大时间线"]')?.click()

    const afterWidth = Number.parseFloat(clip(root).style.width)
    expect(afterWidth).toBeGreaterThan(beforeWidth)
    expect(clip(root).querySelector('[data-clip-label]')?.textContent).toBe('source-a.mp4')
    expect(clip(root).querySelector<HTMLImageElement>('[data-clip-thumbnail]')?.getAttribute('src')).toBe(beforeSrc)
    dispose()
  })

  it('M8 trim and split rederive presentation from the returned TimelineDocument', async () => {
    const { harness, root, dispose } = await mountWorkspace()

    clip(root).click()
    const input = root.querySelector<HTMLInputElement>('[aria-label="裁剪毫秒"]')!
    input.value = '1000'
    clickButton(root, '左裁')

    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(1))
    await vi.waitFor(() => expect(
      clip(root).querySelector<HTMLImageElement>('[data-clip-thumbnail]')?.getAttribute('src'),
    ).toContain('timestamp_ms=4000'))

    seek(root, 3000)
    root.querySelector<HTMLButtonElement>('[data-split-at-playhead]')?.click()
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/split')).toHaveLength(1))
    await vi.waitFor(() => expect(root.querySelector(`[data-clip-id="${SPLIT_RIGHT}"]`)).not.toBeNull())
    expect(root.querySelector(`[data-clip-id="${SPLIT_RIGHT}"] [data-clip-label]`)?.textContent).toBe('source-a.mp4')
    dispose()
  })

  it('M9 undo/redo restore presentation from the same single history', async () => {
    const { root, dispose } = await mountWorkspace()

    clip(root).click()
    const input = root.querySelector<HTMLInputElement>('[aria-label="裁剪毫秒"]')!
    input.value = '1000'
    clickButton(root, '左裁')
    await vi.waitFor(() => expect(clip(root).querySelector('[data-clip-source]')?.textContent).toContain('0:02.0'))

    clickButton(root, '撤销')
    await vi.waitFor(() => expect(clip(root).querySelector('[data-clip-source]')?.textContent).toContain('0:01.0'))

    clickButton(root, '重做')
    await vi.waitFor(() => expect(clip(root).querySelector('[data-clip-source]')?.textContent).toContain('0:02.0'))
    dispose()
  })

  it('M10 candidate replace refreshes source label, marker and thumbnail from existing media data', async () => {
    const { root, dispose } = await mountWorkspace()

    clip(root).click()
    findCandidateCard(root, 'DIRECT').querySelector<HTMLButtonElement>('.finecut-replace')?.click()

    await vi.waitFor(() => expect(clip(root).querySelector('[data-clip-label]')?.textContent).toBe('replacement.mp4'))
    expect(clip(root).dataset.presentationMarker).toBe('S')
    expect(clip(root).querySelector<HTMLImageElement>('[data-clip-thumbnail]')?.getAttribute('src'))
      .toContain(`/api/v1/videos/${MEDIA_REPLACEMENT}/index-thumbnail`)
    dispose()
  })

  it('M11 keeps the Phase 4B Preview Player on the existing source-media path', async () => {
    const { root, dispose } = await mountWorkspace()

    const video = root.querySelector<HTMLVideoElement>('[data-finecut-preview-video]')
    expect(video).not.toBeNull()
    expect(video?.muted).toBe(true)
    expect(video?.getAttribute('src')).toBe(`/api/v1/videos/${MEDIA_A}/source-media`)
    dispose()
  })

  it('M12 keeps snapping, keyboard split and scroll ergonomics on the existing timeline', async () => {
    const { harness, root, dispose } = await mountWorkspace()

    clip(root).click()
    const surface = root.querySelector<HTMLElement>('[data-timeline-surface]')!
    const playhead = root.querySelector<HTMLElement>('[data-playhead]')!
    Object.defineProperty(surface, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ left: 0, right: 960, top: 0, bottom: 186, width: 960, height: 186, x: 0, y: 0, toJSON: () => ({}) }),
    })
    const scale = Number(surface.dataset.pixelsPerSecond)
    playhead.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 0 }))
    window.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: scale * 4.99 }))
    window.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, clientX: scale * 4.99 }))
    expect(root.querySelector<HTMLInputElement>('[aria-label="时间线定位"]')?.value).toBe('5000')

    seek(root, 3000)
    await vi.waitFor(() => expect(
      root.querySelector<HTMLButtonElement>('[data-split-at-playhead]')?.disabled,
    ).toBe(false))
    root.dispatchEvent(new KeyboardEvent('keydown', { key: 's', bubbles: true }))
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/split')).toHaveLength(1))

    const scroll = root.querySelector<HTMLElement>('.finecut-timeline-scroll')!
    scroll.scrollLeft = 0
    scroll.dispatchEvent(new WheelEvent('wheel', {
      bubbles: true,
      cancelable: true,
      shiftKey: true,
      deltaY: 120,
    }))
    expect(scroll.scrollLeft).toBe(120)
    dispose()
  })
})
