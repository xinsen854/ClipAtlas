import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountFineCut } from '../src/index'

const PLAN_ID = '11111111-1111-1111-1111-111111111111'
const CONTEXT_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const CONTEXT_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
const CLIP_A = '44444444-4444-4444-4444-444444444441'
const CLIP_B = '44444444-4444-4444-4444-444444444442'
const SPLIT_RIGHT = '99999999-9999-9999-9999-999999999999'
const MEDIA_A = '66666666-6666-6666-6666-666666666661'
const MEDIA_B = '66666666-6666-6666-6666-666666666662'
const MEDIA_REPLACEMENT = '66666666-6666-6666-6666-666666666663'

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
        source_id: 'segment-b',
        source_path: 'D:/library/source-b.mp4',
        timeline_start_ms: 6000,
        duration_ms: 3000,
        source_in_ms: 2000,
        source_out_ms: 5000,
        opacity: 0.4,
        volume: 0.7,
        transform: { position_x: 12, position_y: -8, scale: 0.9, rotation: 5 },
        effects: [],
      },
    ],
  }],
}

const narration = {
  track_id: '55555555-5555-5555-5555-555555555555',
  revision: 3,
  audio_uri: 'D:/audio/narration.wav',
  duration_ms: 10000,
  segments: [
    { id: CONTEXT_A, text: '句子 A', start_ms: 0, end_ms: 6000 },
    { id: CONTEXT_B, text: '句子 B', start_ms: 6000, end_ms: 10000 },
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
  const directCandidate = {
    requirement_id: `${CONTEXT_A}-DIRECT`,
    sentence_id: CONTEXT_A,
    source_quote: 'DIRECT',
    importance: 'S',
    candidate_type: 'window',
    candidate_id: null,
    media_id: MEDIA_REPLACEMENT,
    source_in_ms: 12000,
    source_out_ms: 19000,
    anchor_in_ms: 12000,
    anchor_out_ms: 12500,
    continuity_status: 'confirmed_continuity',
    display_level: 'S',
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
      return response({ context_id: CONTEXT_A, items: [directCandidate] })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_B}`)) {
      return response({ context_id: CONTEXT_B, items: [] })
    }
    if (url.endsWith(`/finecut/media/${MEDIA_REPLACEMENT}`)) {
      return response({ media_id: MEDIA_REPLACEMENT, source_uri: 'D:/library/replacement.mp4' })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/media-resolution/segment-a`)) {
      return response({ media_id: MEDIA_A, source_uri: 'D:/library/source-a.mp4' })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/media-resolution/segment-b`)) {
      return response({ media_id: MEDIA_B, source_uri: 'D:/library/source-b.mp4' })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/media-resolution/${MEDIA_REPLACEMENT}`)) {
      return response({ media_id: MEDIA_REPLACEMENT, source_uri: 'D:/library/replacement.mp4' })
    }

    if (url.endsWith('/finecut/edit/properties') && method === 'POST') {
      const document = clone(body.document)
      const target = document.tracks[0].clips.find((item: any) => item.id === body.target_clip_id)
      if (!target) return response({ detail: 'clip not found' }, 400)
      if (body.opacity != null) target.opacity = body.opacity
      if (body.volume != null) target.volume = body.volume
      if (body.transform != null) target.transform = { ...target.transform, ...body.transform }
      return response(document)
    }
    if (url.endsWith('/finecut/edit/replace') && method === 'POST') {
      const document = clone(body.document)
      const target = document.tracks[0].clips.find((item: any) => item.id === body.target_clip_id)
      if (!target) return response({ detail: 'clip not found' }, 400)
      target.source_id = body.candidate.media_id
      target.source_path = body.media.source_uri
      target.source_in_ms = body.candidate.source_in_ms
      target.source_out_ms = body.candidate.source_in_ms + target.duration_ms
      return response(document)
    }
    if (url.endsWith('/finecut/edit/trim') && method === 'POST') {
      const document = clone(body.document)
      const target = document.tracks[0].clips.find((item: any) => item.id === body.target_clip_id)
      if (!target || body.delta_ms <= 0 || body.delta_ms >= target.duration_ms) {
        return response({ detail: 'invalid trim' }, 400)
      }
      target.duration_ms -= body.delta_ms
      if (body.edge === 'left') {
        target.timeline_start_ms += body.delta_ms
        target.source_in_ms += body.delta_ms
      } else {
        target.source_out_ms -= body.delta_ms
      }
      return response(document)
    }
    if (url.endsWith('/finecut/edit/split') && method === 'POST') {
      const document = clone(body.document)
      const clips = document.tracks[0].clips
      const index = clips.findIndex((item: any) => item.id === body.target_clip_id)
      if (index < 0) return response({ detail: 'clip not found' }, 400)
      const target = clips[index]
      const end = target.timeline_start_ms + target.duration_ms
      if (!(target.timeline_start_ms < body.split_timeline_ms && body.split_timeline_ms < end)) {
        return response({ detail: 'invalid split' }, 400)
      }
      const leftDuration = body.split_timeline_ms - target.timeline_start_ms
      const sourceSplit = target.source_in_ms + leftDuration
      const left = { ...target, duration_ms: leftDuration, source_out_ms: sourceSplit }
      const right = {
        ...target,
        id: SPLIT_RIGHT,
        timeline_start_ms: body.split_timeline_ms,
        duration_ms: end - body.split_timeline_ms,
        source_in_ms: sourceSplit,
      }
      clips.splice(index, 1, left, right)
      return response(document)
    }
    if (url.endsWith('/finecut/edit/delete') && method === 'POST') {
      const document = clone(body.document)
      document.tracks[0].clips = document.tracks[0].clips
        .filter((item: any) => item.id !== body.target_clip_id)
      return response(document)
    }

    return new Response('not found', { status: 404 })
  })

  return {
    fetchMock,
    requests,
    getSavedTimeline: () => clone(savedTimeline),
  }
}

type Harness = ReturnType<typeof installFetch>

function editCalls(harness: Harness, suffix: string) {
  return harness.requests.filter((item) => item.method === 'POST' && item.url.endsWith(suffix))
}

function clickButton(root: HTMLElement, label: string) {
  const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
    .find((item) => item.textContent === label)
  if (!button) throw new Error(`button not found: ${label}`)
  button.click()
}

function clip(root: HTMLElement, id = CLIP_A): HTMLElement {
  const node = root.querySelector<HTMLElement>(`[data-clip-id="${id}"]`)
  if (!node) throw new Error(`clip not found: ${id}`)
  return node
}

function input(root: HTMLElement, label: string): HTMLInputElement {
  const node = root.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)
  if (!node) throw new Error(`input not found: ${label}`)
  return node
}

function setEffects(
  root: HTMLElement,
  values: {
    opacity?: number
    volume?: number
    positionX?: number
    positionY?: number
    scale?: number
    rotation?: number
  },
) {
  if (values.opacity != null) input(root, '效果透明度').value = String(values.opacity)
  if (values.volume != null) input(root, '效果音量').value = String(values.volume)
  if (values.positionX != null) input(root, '效果位置 X').value = String(values.positionX)
  if (values.positionY != null) input(root, '效果位置 Y').value = String(values.positionY)
  if (values.scale != null) input(root, '效果缩放').value = String(values.scale)
  if (values.rotation != null) input(root, '效果旋转').value = String(values.rotation)
  root.querySelector<HTMLButtonElement>('[data-apply-effects]')?.click()
}

async function mountWorkspace(harness = installFetch()) {
  vi.stubGlobal('fetch', harness.fetchMock)
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

describe('FineCut Phase 6A effects workspace', () => {
  it('E1 selected clip opacity edit returns a new TimelineDocument', async () => {
    const { harness, root, dispose } = await mountWorkspace()
    clip(root).click()
    setEffects(root, { opacity: 0.5 })
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/properties')).toHaveLength(1))
    expect(editCalls(harness, '/finecut/edit/properties')[0].body.opacity).toBe(0.5)
    await vi.waitFor(() => expect(input(root, '效果透明度').value).toBe('0.5'))
    dispose()
  })

  it('E2 opacity uses the existing undo/redo history', async () => {
    const { root, dispose } = await mountWorkspace()
    clip(root).click()
    setEffects(root, { opacity: 0.45 })
    await vi.waitFor(() => expect(input(root, '效果透明度').value).toBe('0.45'))
    clickButton(root, '撤销')
    await vi.waitFor(() => expect(input(root, '效果透明度').value).toBe('1'))
    clickButton(root, '重做')
    await vi.waitFor(() => expect(input(root, '效果透明度').value).toBe('0.45'))
    dispose()
  })

  it('E3 opacity persists through the existing save/reload path', async () => {
    const harness = installFetch()
    const first = await mountWorkspace(harness)
    clip(first.root).click()
    setEffects(first.root, { opacity: 0.33 })
    await vi.waitFor(() => expect(input(first.root, '效果透明度').value).toBe('0.33'))
    clickButton(first.root, '保存')
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips[0].opacity).toBe(0.33))
    first.dispose()
    first.root.remove()

    const second = await mountWorkspace(harness)
    clip(second.root).click()
    expect(input(second.root, '效果透明度').value).toBe('0.33')
    second.dispose()
  })

  it('E4 volume edit updates TimelineDocument', async () => {
    const { harness, root, dispose } = await mountWorkspace()
    clip(root).click()
    setEffects(root, { volume: 0.25 })
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/properties')).toHaveLength(1))
    expect(editCalls(harness, '/finecut/edit/properties')[0].body.volume).toBe(0.25)
    await vi.waitFor(() => expect(input(root, '效果音量').value).toBe('0.25'))
    dispose()
  })

  it('E5 volume editing never unmutes the existing V1 Preview Player', async () => {
    const { root, dispose } = await mountWorkspace()
    clip(root).click()
    setEffects(root, { volume: 0.2 })
    await vi.waitFor(() => expect(input(root, '效果音量').value).toBe('0.2'))
    const video = root.querySelector<HTMLVideoElement>('[data-finecut-preview-video]')!
    expect(video.muted).toBe(true)
    expect(video.defaultMuted).toBe(true)
    dispose()
  })

  it('E6 transform edits use only position_x position_y scale rotation', async () => {
    const { harness, root, dispose } = await mountWorkspace()
    clip(root).click()
    setEffects(root, { positionX: 30, positionY: -20, scale: 1.2, rotation: 18 })
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/properties')).toHaveLength(1))
    expect(editCalls(harness, '/finecut/edit/properties')[0].body.transform).toEqual({
      position_x: 30,
      position_y: -20,
      scale: 1.2,
      rotation: 18,
    })
    dispose()
  })

  it('E7 transform edits share existing undo/redo history', async () => {
    const { root, dispose } = await mountWorkspace()
    clip(root).click()
    setEffects(root, { positionX: 40, scale: 1.4 })
    await vi.waitFor(() => expect(input(root, '效果位置 X').value).toBe('40'))
    clickButton(root, '撤销')
    await vi.waitFor(() => expect(input(root, '效果位置 X').value).toBe('0'))
    expect(input(root, '效果缩放').value).toBe('1')
    clickButton(root, '重做')
    await vi.waitFor(() => expect(input(root, '效果位置 X').value).toBe('40'))
    expect(input(root, '效果缩放').value).toBe('1.4')
    dispose()
  })

  it('E8 Preview opacity and CSS transform are derived from TimelineDocument', async () => {
    const { root, dispose } = await mountWorkspace()
    clip(root).click()
    setEffects(root, { opacity: 0.6, positionX: 25, positionY: -15, scale: 1.1, rotation: 9 })
    await vi.waitFor(() => {
      const video = root.querySelector<HTMLVideoElement>('[data-finecut-preview-video]')!
      expect(video.style.opacity).toBe('0.6')
      expect(video.style.transform).toBe('translate(25px, -15px) scale(1.1) rotate(9deg)')
    })
    dispose()
  })

  it('E9 selecting a different clip re-derives Effects panel values', async () => {
    const { root, dispose } = await mountWorkspace()
    clip(root).click()
    expect(input(root, '效果透明度').value).toBe('1')
    clip(root, CLIP_B).click()
    await vi.waitFor(() => expect(input(root, '效果透明度').value).toBe('0.4'))
    expect(input(root, '效果音量').value).toBe('0.7')
    expect(input(root, '效果位置 X').value).toBe('12')
    expect(input(root, '效果位置 Y').value).toBe('-8')
    expect(input(root, '效果缩放').value).toBe('0.9')
    expect(input(root, '效果旋转').value).toBe('5')
    dispose()
  })

  it('E10 replace trim and split preserve clip effects without a second state', async () => {
    const { harness, root, dispose } = await mountWorkspace()
    clip(root).click()
    setEffects(root, { opacity: 0.52, positionX: 16, scale: 1.15 })
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/properties')).toHaveLength(1))
    await vi.waitFor(() => expect(root.querySelector<HTMLButtonElement>('[data-apply-effects]')?.disabled).toBe(false))
    expect(input(root, '效果透明度').value).toBe('0.52')

    const direct = Array.from(root.querySelectorAll<HTMLElement>('.finecut-card'))
      .find((item) => item.textContent?.includes('DIRECT'))!
    direct.querySelector<HTMLButtonElement>('.finecut-replace')?.click()
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/replace')).toHaveLength(1))
    await vi.waitFor(() => expect(root.querySelector<HTMLButtonElement>('[data-apply-effects]')?.disabled).toBe(false))
    expect(input(root, '效果透明度').value).toBe('0.52')
    expect(input(root, '效果位置 X').value).toBe('16')

    input(root, '裁剪毫秒').value = '500'
    clickButton(root, '右裁')
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(1))
    await vi.waitFor(() => expect(root.querySelector<HTMLButtonElement>('[data-apply-effects]')?.disabled).toBe(false))
    expect(input(root, '效果透明度').value).toBe('0.52')

    const seek = input(root, '时间线定位')
    seek.value = '2500'
    seek.dispatchEvent(new Event('input', { bubbles: true }))
    await vi.waitFor(() => expect(root.querySelector<HTMLButtonElement>('[data-split-at-playhead]')?.disabled).toBe(false))
    root.querySelector<HTMLButtonElement>('[data-split-at-playhead]')?.click()
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/split')).toHaveLength(1))
    await vi.waitFor(() => expect(root.querySelector(`[data-clip-id="${SPLIT_RIGHT}"]`)).not.toBeNull())
    clip(root, SPLIT_RIGHT).click()
    expect(input(root, '效果透明度').value).toBe('0.52')
    expect(input(root, '效果位置 X').value).toBe('16')
    dispose()
  })

  it('E11 deleting the selected clip clears Effects panel safely', async () => {
    const { root, dispose } = await mountWorkspace()
    clip(root, CLIP_B).click()
    await vi.waitFor(() => expect(input(root, '效果透明度').value).toBe('0.4'))
    clickButton(root, '删除镜头')
    await vi.waitFor(() => expect(root.querySelector('[data-effects-empty]')).not.toBeNull())
    expect(root.querySelector('[data-apply-effects]')).toBeNull()
    dispose()
  })

  it('E12 Phase 5B labels and derived thumbnails survive Effects edits', async () => {
    const { root, dispose } = await mountWorkspace()
    clip(root).click()
    await vi.waitFor(() => expect(clip(root).querySelector('[data-clip-thumbnail]')).not.toBeNull())
    const label = clip(root).querySelector('[data-clip-label]')?.textContent
    const thumbnail = clip(root).querySelector<HTMLImageElement>('[data-clip-thumbnail]')?.getAttribute('src')
    setEffects(root, { opacity: 0.7 })
    await vi.waitFor(() => expect(input(root, '效果透明度').value).toBe('0.7'))
    expect(clip(root).querySelector('[data-clip-label]')?.textContent).toBe(label)
    expect(clip(root).querySelector<HTMLImageElement>('[data-clip-thumbnail]')?.getAttribute('src')).toBe(thumbnail)
    dispose()
  })

  it('E13 Phase 5A snapping keyboard split and horizontal scroll still work', async () => {
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
    expect(input(root, '时间线定位').value).toBe('5000')

    const seek = input(root, '时间线定位')
    seek.value = '3000'
    seek.dispatchEvent(new Event('input', { bubbles: true }))
    root.dispatchEvent(new KeyboardEvent('keydown', { key: 's', bubbles: true }))
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/split')).toHaveLength(1))

    const scroll = root.querySelector<HTMLElement>('.finecut-timeline-scroll')!
    scroll.scrollLeft = 0
    scroll.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, shiftKey: true, deltaY: 120 }))
    expect(scroll.scrollLeft).toBe(120)
    dispose()
  })

  it('E14 Phase 4B Preview Player keeps source-media and muted semantics', async () => {
    const { root, dispose } = await mountWorkspace()
    clip(root).click()
    setEffects(root, { opacity: 0.75, volume: 0.1 })
    await vi.waitFor(() => expect(input(root, '效果透明度').value).toBe('0.75'))
    const video = root.querySelector<HTMLVideoElement>('[data-finecut-preview-video]')!
    expect(video.getAttribute('src')).toBe(`/api/v1/videos/${MEDIA_A}/source-media`)
    expect(video.muted).toBe(true)
    dispose()
  })

  it('E15 Phase 4C visual trim and delete controls remain wired to existing edit operations', async () => {
    const { harness, root, dispose } = await mountWorkspace()
    clip(root).click()
    const handle = root.querySelector<HTMLButtonElement>('[data-trim-handle="right"]')!
    handle.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 400 }))
    window.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, clientX: 360 }))
    await vi.waitFor(() => expect(editCalls(harness, '/finecut/edit/trim')).toHaveLength(1))
    expect(root.querySelector('[data-visual-delete]')).not.toBeNull()
    dispose()
  })
})