import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountFineCut } from '../src/index'

const PLAN_ID = '11111111-1111-1111-1111-111111111111'
const CONTEXT_ID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const CLIP_ID = '44444444-4444-4444-4444-444444444444'
const RIGHT_CLIP_ID = '99999999-9999-9999-9999-999999999999'

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
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/timeline`) && method === 'GET') {
      return response(clone(savedTimeline))
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/timeline`) && method === 'PUT') {
      savedTimeline = JSON.parse(String(init?.body))
      return response(clone(savedTimeline))
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/narration`)) return response(narration)
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_ID}`)) {
      return response({ context_id: CONTEXT_ID, items: [] })
    }

    if (url.endsWith('/finecut/edit/trim') && method === 'POST') {
      const body = JSON.parse(String(init?.body))
      const document = clone(body.document)
      const clip = document.tracks[0].clips.find((item: typeof initialTimeline.tracks[0]['clips'][0]) => item.id === body.target_clip_id)
      if (!clip || body.delta_ms <= 0 || body.delta_ms >= clip.duration_ms) return response({ detail: 'invalid trim' }, 400)
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
      const body = JSON.parse(String(init?.body))
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
      const body = JSON.parse(String(init?.body))
      const document = clone(body.document)
      document.tracks[0].clips = document.tracks[0].clips.filter(
        (item: typeof initialTimeline.tracks[0]['clips'][0]) => item.id !== body.target_clip_id,
      )
      return response(document)
    }

    return new Response('not found', { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { getSavedTimeline: () => clone(savedTimeline) }
}

function findButton(root: HTMLElement, label: string): HTMLButtonElement {
  const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
    .find((item) => item.textContent === label)
  if (!button) throw new Error(`button not found: ${label}`)
  return button
}

async function waitForSaveReady(root: HTMLElement): Promise<void> {
  await vi.waitFor(() => expect(findButton(root, '保存').disabled).toBe(false))
}

async function mountSelectedClip() {
  const harness = installFetch()
  const root = document.createElement('div')
  document.body.append(root)
  const dispose = mountFineCut(root, { planId: PLAN_ID })
  await vi.waitFor(() => expect(root.querySelector(`[data-clip-id="${CLIP_ID}"]`)).not.toBeNull())
  root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_ID}"]`)?.click()
  return { harness, root, dispose }
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.replaceChildren()
})

describe('FineCut Phase 3B editing', () => {
  it('left trims 1:1 and undo/redo restores the snapshots', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    const input = root.querySelector<HTMLInputElement>('[aria-label="裁剪毫秒"]')
    expect(input).not.toBeNull()
    if (input) input.value = '500'
    findButton(root, '左裁').click()

    await vi.waitFor(() => expect(findButton(root, '撤销').disabled).toBe(false))
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips[0].timeline_start_ms).toBe(500))
    expect(harness.getSavedTimeline().tracks[0].clips[0].source_in_ms).toBe(1500)
    expect(harness.getSavedTimeline().tracks[0].clips[0].duration_ms).toBe(4500)
    await waitForSaveReady(root)

    findButton(root, '撤销').click()
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips[0].timeline_start_ms).toBe(0))
    await waitForSaveReady(root)

    findButton(root, '重做').click()
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips[0].timeline_start_ms).toBe(500))
    dispose()
  })

  it('splits at the playhead with continuous timeline/source and supports undo redo', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    const seek = root.querySelector<HTMLInputElement>('[aria-label="时间线定位"]')
    expect(seek).not.toBeNull()
    if (seek) {
      seek.value = '2500'
      seek.dispatchEvent(new Event('input', { bubbles: true }))
    }
    findButton(root, '在播放头拆分').click()

    await vi.waitFor(() => expect(findButton(root, '撤销').disabled).toBe(false))
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips).toHaveLength(2))
    let [left, right] = harness.getSavedTimeline().tracks[0].clips
    expect(left.timeline_start_ms + left.duration_ms).toBe(right.timeline_start_ms)
    expect(left.source_out_ms).toBe(right.source_in_ms)
    await waitForSaveReady(root)

    findButton(root, '撤销').click()
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips).toHaveLength(1))
    await waitForSaveReady(root)

    findButton(root, '重做').click()
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips).toHaveLength(2))
    ;[left, right] = harness.getSavedTimeline().tracks[0].clips
    expect(left.source_out_ms).toBe(right.source_in_ms)
    dispose()
  })

  it('deletes only the selected clip and undo/redo restores it without ripple', async () => {
    const { harness, root, dispose } = await mountSelectedClip()
    findButton(root, '删除镜头').click()

    await vi.waitFor(() => expect(findButton(root, '撤销').disabled).toBe(false))
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips).toHaveLength(0))
    await waitForSaveReady(root)

    findButton(root, '撤销').click()
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips).toHaveLength(1))
    expect(harness.getSavedTimeline().tracks[0].clips[0].timeline_start_ms).toBe(0)
    await waitForSaveReady(root)

    findButton(root, '重做').click()
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips).toHaveLength(0))
    dispose()
  })
})
