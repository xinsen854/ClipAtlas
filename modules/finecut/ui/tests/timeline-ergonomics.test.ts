import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountFineCut } from '../src/index'

const PLAN_ID = '11111111-1111-1111-1111-111111111111'
const CONTEXT_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const CONTEXT_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
const CONTEXT_C = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
const CLIP_A = '44444444-4444-4444-4444-444444444441'
const CLIP_B = '44444444-4444-4444-4444-444444444442'
const RIGHT_CLIP_ID = '99999999-9999-9999-9999-999999999999'
const MEDIA_A = '66666666-6666-6666-6666-666666666661'
const MEDIA_B = '66666666-6666-6666-6666-666666666662'

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
        source_id: 'source-a',
        source_path: 'D:/media/a.mp4',
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
        source_id: 'source-b',
        source_path: 'D:/media/b.mp4',
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
    { id: CONTEXT_A, text: '句子 A', start_ms: 0, end_ms: 3000 },
    { id: CONTEXT_B, text: '句子 B', start_ms: 3000, end_ms: 7000 },
    { id: CONTEXT_C, text: '句子 C', start_ms: 7000, end_ms: 12000 },
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
    if (url.includes(`/finecut/plans/${PLAN_ID}/candidates/`)) {
      const contextId = decodeURIComponent(url.split('/').at(-1) ?? '')
      return response({ context_id: contextId, items: [] })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/media-resolution/source-a`)) {
      return response({ media_id: MEDIA_A, source_uri: 'D:/media/a.mp4' })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/media-resolution/source-b`)) {
      return response({ media_id: MEDIA_B, source_uri: 'D:/media/b.mp4' })
    }

    if (url.endsWith('/finecut/edit/trim') && method === 'POST') {
      const document = clone(body.document)
      const clip = document.tracks[0].clips.find(
        (item: typeof initialTimeline.tracks[0]['clips'][0]) => item.id === body.target_clip_id,
      )
      if (!clip || body.delta_ms <= 0 || body.delta_ms >= clip.duration_ms) {
        return response({ detail: 'invalid trim' }, 400)
      }
      clip.duration_ms -= body.delta_ms
      if (body.edge === 'left') {
        clip.timeline_start_ms += body.delta_ms
        clip.source_in_ms += body.delta_ms
      } else if (body.edge === 'right') {
        clip.source_out_ms -= body.delta_ms
      } else {
        return response({ detail: 'invalid trim edge' }, 400)
      }
      return response(document)
    }

    if (url.endsWith('/finecut/edit/split') && method === 'POST') {
      const document = clone(body.document)
      const clips = document.tracks[0].clips
      const index = clips.findIndex(
        (item: typeof initialTimeline.tracks[0]['clips'][0]) => item.id === body.target_clip_id,
      )
      if (index < 0) return response({ detail: 'target clip not found' }, 400)
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
        id: RIGHT_CLIP_ID,
        timeline_start_ms: body.split_timeline_ms,
        duration_ms: end - body.split_timeline_ms,
        source_in_ms: sourceSplit,
      }
      clips.splice(index, 1, left, right)
      return response(document)
    }

    if (url.endsWith('/finecut/edit/delete') && method === 'POST') {
      const document = clone(body.document)
      document.tracks[0].clips = document.tracks[0].clips.filter(
        (item: typeof initialTimeline.tracks[0]['clips'][0]) => item.id !== body.target_clip_id,
      )
      return response(document)
    }

    return new Response('not found', { status: 404 })
  })

  vi.stubGlobal('fetch', fetchMock)
  return {
    fetchMock,
    requests,
    getSavedTimeline: () => clone(savedTimeline),
  }
}

function editCalls(harness: ReturnType<typeof installFetch>, suffix: string) {
  return harness.requests.filter((item) => item.url.endsWith(suffix) && item.method === 'POST')
}

function putCalls(harness: ReturnType<typeof installFetch>) {
  return harness.requests.filter((item) => item.method === 'PUT')
}

async function mountSelectedClip() {
  const harness = installFetch()
  const root = document.createElement('div')
  document.body.append(root)
  const dispose = mountFineCut(root, { planId: PLAN_ID })
  await vi.waitFor(() => expect(root.querySelector(`[data-clip-id="${CLIP_A}"]`)).not.toBeNull())
  root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_A}"]`)?.click()
  await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
  return { harness, root, dispose }
}

function timelineScale(root: HTMLElement): number {
  return Number(root.querySelector<HTMLElement>('[data-timeline-surface]')?.dataset.pixelsPerSecond)
}

function dragHandle(root: HTMLElement, edge: 'left' | 'right', fromX: number, toX: number) {
  const handle = root.querySelector<HTMLElement>(`[data-trim-handle="${edge}"]`)
  expect(handle).not.toBeNull()
  if (!handle) return
  handle.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: fromX }))
  window.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: toX }))
  window.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, clientX: toX }))
}

function dragPlayhead(root: HTMLElement, toTimelineMs: number) {
  const surface = root.querySelector<HTMLElement>('[data-timeline-surface]')
  const playhead = root.querySelector<HTMLElement>('[data-playhead]')
  expect(surface).not.toBeNull()
  expect(playhead).not.toBeNull()
  if (!surface || !playhead) return
  Object.defineProperty(surface, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({ left: 0, right: 960, top: 0, bottom: 186, width: 960, height: 186, x: 0, y: 0, toJSON: () => ({}) }),
  })
  const x = toTimelineMs / 1000 * timelineScale(root)
  playhead.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 0 }))
  window.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: x }))
  window.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, clientX: x }))
}

function seek(root: HTMLElement, value: number) {
  const input = root.querySelector<HTMLInputElement>('[aria-label="时间线定位"]')
  expect(input).not.toBeNull()
  if (!input) return
  input.value = String(value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function key(target: EventTarget, value: string, options: KeyboardEventInit = {}) {
  target.dispatchEvent(new KeyboardEvent('keydown', {
    key: value,
    bubbles: true,
    cancelable: true,
    ...options,
  }))
}

function mockPlayback(video: HTMLVideoElement) {
  let paused = true
  const play = vi.fn(async () => {
    paused = false
  })
  const pause = vi.fn(() => {
    paused = true
  })
  Object.defineProperty(video, 'paused', { configurable: true, get: () => paused })
  Object.defineProperty(video, 'play', { configurable: true, value: play })
  Object.defineProperty(video, 'pause', { configurable: true, value: pause })
  return { play, pause }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.replaceChildren()
})

describe('FineCut Phase 5A timeline editing ergonomics', () => {
  it('E1 snaps a visual left trim to an existing narration boundary and still calls existing trim', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    const scale = timelineScale(root)

    dragHandle(root, 'left', 100, 100 + scale * 2.93)

    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(1))
    const call = editCalls(harness, '/finecut/edit/trim')[0]
    expect(call.body.edge).toBe('left')
    expect(call.body.delta_ms).toBe(3000)
    expect(call.body.document.tracks[0].clips[0].timeline_start_ms).toBe(0)
    expect(call.body.document.tracks[0].clips[0].duration_ms).toBe(5000)
    dispose()
  })

  it('E2 snaps playhead dragging to deterministic clip/narration boundaries', async () => {
    const { root, dispose } = await mountSelectedClip()

    dragPlayhead(root, 2940)

    expect(root.querySelector<HTMLInputElement>('[aria-label="时间线定位"]')?.value).toBe('3000')
    dispose()
  })

  it('E3 keeps raw playhead milliseconds when no deterministic snap point is within threshold', async () => {
    const { root, dispose } = await mountSelectedClip()

    dragPlayhead(root, 2800)

    expect(root.querySelector<HTMLInputElement>('[aria-label="时间线定位"]')?.value).toBe('2800')
    dispose()
  })

  it('E4 keyboard split and delete reuse the existing editing operations', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    seek(root, 2500)

    key(root, 's')
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/split')).toHaveLength(1))
    expect(editCalls(harness, '/finecut/edit/split')[0].body.split_timeline_ms).toBe(2500)
    await vi.waitFor(() => expect(root.querySelectorAll('[data-clip-id]')).toHaveLength(3))

    key(root, 'Delete')
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/delete')).toHaveLength(1))
    dispose()
  })

  it('E5 keyboard undo redo and save feed the existing single history/save path', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    const scale = timelineScale(root)

    dragHandle(root, 'left', 100, 100 + scale * 0.5)
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(1))
    await vi.waitFor(() => {
      expect(root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_A}"]`)?.style.left).toBe(`${scale * 0.5}px`)
    })

    key(root, 'z', { ctrlKey: true })
    await vi.waitFor(() => {
      expect(root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_A}"]`)?.style.left).toBe('0px')
    })

    key(root, 'z', { ctrlKey: true, shiftKey: true })
    await vi.waitFor(() => {
      expect(root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_A}"]`)?.style.left).toBe(`${scale * 0.5}px`)
    })

    key(root, 's', { ctrlKey: true })
    await vi.waitFor(() => expect(putCalls(harness)).toHaveLength(1))
    expect(harness.getSavedTimeline().tracks[0].clips[0].timeline_start_ms).toBe(500)
    expect(harness.getSavedTimeline().tracks[0].clips[0].source_in_ms).toBe(1500)
    dispose()
  })

  it('E6 input textarea and contenteditable focus never trigger destructive timeline shortcuts', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    seek(root, 2500)

    const input = root.querySelector<HTMLInputElement>('[aria-label="裁剪毫秒"]')!
    key(input, 's')
    key(input, 'Delete')

    const textarea = document.createElement('textarea')
    root.append(textarea)
    key(textarea, 's')
    key(textarea, 'Delete')

    const editable = document.createElement('div')
    editable.setAttribute('contenteditable', 'true')
    root.append(editable)
    key(editable, 's')
    key(editable, 'Delete')

    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(editCalls(harness, '/finecut/edit/split')).toHaveLength(0)
    expect(editCalls(harness, '/finecut/edit/delete')).toHaveLength(0)
    dispose()
  })

  it('E7 Space toggles the existing preview player instead of creating a second clock', async () => {
    const { root, dispose } = await mountSelectedClip()
    const video = root.querySelector<HTMLVideoElement>('[data-finecut-preview-video]')!
    const playback = mockPlayback(video)

    key(root, ' ')
    expect(playback.play).toHaveBeenCalledTimes(1)

    key(root, ' ')
    expect(playback.pause).toHaveBeenCalledTimes(1)
    dispose()
  })

  it('E8 Shift+wheel navigates the existing horizontal scroll container and remains ephemeral', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    const scroll = root.querySelector<HTMLElement>('.finecut-timeline-scroll')!
    Object.defineProperty(scroll, 'clientWidth', { configurable: true, value: 240 })
    scroll.scrollLeft = 0

    scroll.dispatchEvent(new WheelEvent('wheel', {
      bubbles: true,
      cancelable: true,
      shiftKey: true,
      deltaY: 120,
    }))

    expect(scroll.scrollLeft).toBe(120)
    const save = Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent === '保存')!
    save.click()
    await vi.waitFor(() => expect(putCalls(harness)).toHaveLength(1))
    expect(putCalls(harness)[0].body).toEqual(initialTimeline)
    expect(putCalls(harness)[0].body).not.toHaveProperty('timelineScrollLeft')
    dispose()
  })

  it('E9 playhead movement keeps the playhead visible using only the existing scroll container', async () => {
    const { root, dispose } = await mountSelectedClip()
    const scroll = root.querySelector<HTMLElement>('.finecut-timeline-scroll')!
    Object.defineProperty(scroll, 'clientWidth', { configurable: true, value: 120 })
    scroll.scrollLeft = 0

    seek(root, 8000)

    await vi.waitFor(() => {
      expect(root.querySelector<HTMLElement>('.finecut-timeline-scroll')?.scrollLeft).toBeGreaterThan(0)
    })
    dispose()
  })

  it('E10 Ctrl/Cmd+wheel changes only pixelsPerSecond while ordinary wheel leaves zoom alone', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    let scroll = root.querySelector<HTMLElement>('.finecut-timeline-scroll')!
    expect(timelineScale(root)).toBe(80)

    scroll.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: -100 }))
    expect(timelineScale(root)).toBe(80)

    scroll.dispatchEvent(new WheelEvent('wheel', {
      bubbles: true,
      cancelable: true,
      ctrlKey: true,
      deltaY: -100,
    }))

    await vi.waitFor(() => expect(timelineScale(root)).toBe(120))
    expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(0)
    expect(editCalls(harness, '/finecut/edit/split')).toHaveLength(0)
    expect(editCalls(harness, '/finecut/edit/delete')).toHaveLength(0)
    scroll = root.querySelector<HTMLElement>('.finecut-timeline-scroll')!
    expect(scroll).not.toBeNull()
    dispose()
  })
})
