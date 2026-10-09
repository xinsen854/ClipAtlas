import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountFineCut } from '../src/index'

const PLAN_ID = '11111111-1111-1111-1111-111111111111'
const CONTEXT_ID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const CLIP_ID = '44444444-4444-4444-4444-444444444444'
const RIGHT_CLIP_ID = '99999999-9999-9999-9999-999999999999'
const MEDIA_ID = '66666666-6666-6666-6666-666666666666'

const initialTimeline = {
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
    clips: [{
      id: CLIP_ID,
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
    }],
  }],
}

const narration = {
  track_id: '55555555-5555-5555-5555-555555555555',
  revision: 1,
  audio_uri: 'D:/audio/narration.wav',
  duration_ms: 10000,
  segments: [{ id: CONTEXT_ID, text: '句子 A', start_ms: 0, end_ms: 5000 }],
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
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_ID}`)) {
      return response({ context_id: CONTEXT_ID, items: [] })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/media-resolution/source-a`)) {
      return response({ media_id: MEDIA_ID, source_uri: 'D:/media/a.mp4' })
    }

    if (url.endsWith('/finecut/edit/trim') && method === 'POST') {
      const document = clone(body.document)
      const clip = document.tracks[0].clips.find((item: typeof initialTimeline.tracks[0]['clips'][0]) => item.id === body.target_clip_id)
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
      const index = clips.findIndex((item: typeof initialTimeline.tracks[0]['clips'][0]) => item.id === body.target_clip_id)
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

function findButton(root: HTMLElement, label: string): HTMLButtonElement {
  const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
    .find((item) => item.textContent === label)
  if (!button) throw new Error(`button not found: ${label}`)
  return button
}

async function mountSelectedClip() {
  const harness = installFetch()
  const root = document.createElement('div')
  document.body.append(root)
  const dispose = mountFineCut(root, { planId: PLAN_ID })
  await vi.waitFor(() => expect(root.querySelector(`[data-clip-id="${CLIP_ID}"]`)).not.toBeNull())
  root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_ID}"]`)?.click()
  await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
  return { harness, root, dispose }
}

function dragHandle(root: HTMLElement, edge: 'left' | 'right', fromX: number, toX: number) {
  const handle = root.querySelector<HTMLElement>(`[data-trim-handle="${edge}"]`)
  expect(handle).not.toBeNull()
  if (!handle) return
  handle.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: fromX }))
  window.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: toX }))
  window.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, clientX: toX }))
}

function seek(root: HTMLElement, value: number) {
  const input = root.querySelector<HTMLInputElement>('[aria-label="时间线定位"]')
  expect(input).not.toBeNull()
  if (!input) return
  input.value = String(value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function editCalls(harness: ReturnType<typeof installFetch>, suffix: string) {
  return harness.requests.filter((item) => item.url.endsWith(suffix) && item.method === 'POST')
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.replaceChildren()
})

describe('FineCut Phase 4C visual editing controls', () => {
  it('C1 shows trim handles and visual split/delete controls only for the selected V1 clip', async () => {
    const harness = installFetch()
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })
    await vi.waitFor(() => expect(root.querySelector(`[data-clip-id="${CLIP_ID}"]`)).not.toBeNull())

    expect(root.querySelector('[data-trim-handle]')).toBeNull()
    expect(root.querySelector('[data-visual-split]')).toBeNull()
    expect(root.querySelector('[data-visual-delete]')).toBeNull()

    root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_ID}"]`)?.click()

    expect(root.querySelector('[data-trim-handle="left"]')).not.toBeNull()
    expect(root.querySelector('[data-trim-handle="right"]')).not.toBeNull()
    expect(root.querySelector('[data-visual-split]')).not.toBeNull()
    expect(root.querySelector('[data-visual-delete]')).not.toBeNull()
    expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(0)
    dispose()
  })

  it('C2 left handle converts inward pixels to delta_ms and uses existing trim operation', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    seek(root, 2500)
    const scale = Number(root.querySelector<HTMLElement>('[data-timeline-surface]')?.dataset.pixelsPerSecond)

    dragHandle(root, 'left', 100, 100 + scale * 0.5)

    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(1))
    const call = editCalls(harness, '/finecut/edit/trim')[0]
    expect(call.body.edge).toBe('left')
    expect(call.body.delta_ms).toBe(500)
    expect(call.body.document.tracks[0].clips[0].timeline_start_ms).toBe(0)
    expect(call.body.document.tracks[0].clips[0].source_in_ms).toBe(1000)

    await vi.waitFor(() => {
      const clip = root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_ID}"]`)
      expect(clip?.style.left).toBe(`${scale * 0.5}px`)
      expect(clip?.style.width).toBe(`${scale * 4.5}px`)
    })

    await vi.waitFor(() => expect(root.querySelector('[data-finecut-preview-video]')).not.toBeNull())
    const video = root.querySelector<HTMLVideoElement>('[data-finecut-preview-video]')!
    video.dispatchEvent(new Event('loadedmetadata'))
    expect(video.currentTime).toBeCloseTo(3.5, 3)
    dispose()
  })

  it('C3 right handle converts inward pixels to delta_ms and uses existing trim operation', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    const scale = Number(root.querySelector<HTMLElement>('[data-timeline-surface]')?.dataset.pixelsPerSecond)

    dragHandle(root, 'right', 500, 500 - scale * 0.5)

    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(1))
    const call = editCalls(harness, '/finecut/edit/trim')[0]
    expect(call.body.edge).toBe('right')
    expect(call.body.delta_ms).toBe(500)
    expect(call.body.document.tracks[0].clips[0].source_out_ms).toBe(6000)

    await vi.waitFor(() => {
      const clip = root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_ID}"]`)
      expect(clip?.style.left).toBe('0px')
      expect(clip?.style.width).toBe(`${scale * 4.5}px`)
    })
    dispose()
  })

  it('C4 outward trim gesture is ignored and does not invent clip-extension semantics', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    const before = root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_ID}"]`)?.style.width

    dragHandle(root, 'left', 100, 60)
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(0)
    expect(root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_ID}"]`)?.style.width).toBe(before)
    dispose()
  })

  it('C5 visual split control uses the existing split endpoint at the single playheadMs', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    seek(root, 2500)

    const split = root.querySelector<HTMLButtonElement>('[data-visual-split]')
    expect(split).not.toBeNull()
    expect(split?.disabled).toBe(false)
    split?.click()

    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/split')).toHaveLength(1))
    const call = editCalls(harness, '/finecut/edit/split')[0]
    expect(call.body.split_timeline_ms).toBe(2500)
    await vi.waitFor(() => expect(root.querySelectorAll('[data-clip-id]')).toHaveLength(2))
    dispose()
  })

  it('C6 visual delete control uses existing delete without ripple and preview follows the returned timeline', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    const remove = root.querySelector<HTMLButtonElement>('[data-visual-delete]')
    expect(remove).not.toBeNull()
    remove?.click()

    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/delete')).toHaveLength(1))
    await vi.waitFor(() => expect(root.querySelector(`[data-clip-id="${CLIP_ID}"]`)).toBeNull())
    expect(root.textContent?.toLowerCase()).toContain('gap')
    dispose()
  })

  it('C7 visual edit feeds the existing undo/redo/save history instead of a second editing state', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    const scale = Number(root.querySelector<HTMLElement>('[data-timeline-surface]')?.dataset.pixelsPerSecond)

    dragHandle(root, 'left', 100, 100 + scale * 0.5)
    await vi.waitFor(() => expect(findButton(root, '撤销').disabled).toBe(false))

    findButton(root, '撤销').click()
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips[0].timeline_start_ms).toBe(0))
    await vi.waitFor(() => expect(findButton(root, '保存').disabled).toBe(false))

    findButton(root, '重做').click()
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips[0].timeline_start_ms).toBe(500))
    expect(harness.getSavedTimeline().tracks[0].clips[0].source_in_ms).toBe(1500)
    dispose()
  })
})
