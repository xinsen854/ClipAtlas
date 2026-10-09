import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountFineCut } from '../src/index'

const PLAN_ID = '11111111-1111-1111-1111-111111111111'
const CONTEXT_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const CONTEXT_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
const CLIP_A = '44444444-4444-4444-4444-444444444441'
const CLIP_B = '44444444-4444-4444-4444-444444444442'
const CLIP_NO_CONTEXT = '44444444-4444-4444-4444-444444444443'
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
        source_id: 'source-a',
        source_path: 'D:/media/a.mp4',
        timeline_start_ms: 1000,
        duration_ms: 2000,
        source_in_ms: 1000,
        source_out_ms: 3000,
        opacity: 1,
        volume: 1,
        transform: {},
        effects: [],
      },
      {
        id: CLIP_B,
        source_id: 'source-b',
        source_path: 'D:/media/b.mp4',
        timeline_start_ms: 5000,
        duration_ms: 2000,
        source_in_ms: 0,
        source_out_ms: 2000,
        opacity: 1,
        volume: 1,
        transform: {},
        effects: [],
      },
      {
        id: CLIP_NO_CONTEXT,
        source_id: 'source-c',
        source_path: 'D:/media/c.mp4',
        timeline_start_ms: 8500,
        duration_ms: 1000,
        source_in_ms: 0,
        source_out_ms: 1000,
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
    { id: CONTEXT_A, text: '句子 A', start_ms: 0, end_ms: 5000 },
    { id: CONTEXT_B, text: '句子 B', start_ms: 5000, end_ms: 8000 },
  ],
}

function candidate(contextId: string, label: string, mediaId: string) {
  return {
    requirement_id: `${contextId}-${label}`,
    sentence_id: contextId,
    source_quote: label,
    importance: 'S',
    candidate_type: 'window',
    candidate_id: null,
    media_id: mediaId,
    source_in_ms: 0,
    source_out_ms: 4000,
    anchor_in_ms: null,
    anchor_out_ms: null,
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
}

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function installFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/timeline`)) return response(timeline)
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/narration`)) return response(narration)
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_A}`)) {
      return response({ context_id: CONTEXT_A, items: [candidate(CONTEXT_A, 'A-CANDIDATE', MEDIA_A)] })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_B}`)) {
      return response({ context_id: CONTEXT_B, items: [candidate(CONTEXT_B, 'B-CANDIDATE', MEDIA_B)] })
    }
    if (url.endsWith(`/finecut/media/${MEDIA_A}`)) return response({ media_id: MEDIA_A, source_uri: 'D:/media/a.mp4' })
    if (url.endsWith(`/finecut/media/${MEDIA_B}`)) return response({ media_id: MEDIA_B, source_uri: 'D:/media/b.mp4' })
    return new Response('not found', { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function mountWorkspace() {
  const fetchMock = installFetch()
  const root = document.createElement('div')
  document.body.append(root)
  const dispose = mountFineCut(root, { planId: PLAN_ID })
  await vi.waitFor(() => expect(root.textContent).toContain('A-CANDIDATE'))
  return { root, dispose, fetchMock }
}

function px(value: string): number {
  return Number.parseFloat(value.replace('px', ''))
}

function candidateCalls(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.includes('/candidates/'))
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.replaceChildren()
})

describe('FineCut Phase 4A visual timeline', () => {
  it('renders V1/T1/A1 and derives clip geometry directly from timeline time', async () => {
    const { root, dispose } = await mountWorkspace()

    expect(root.querySelector('[data-track="V1"]')).not.toBeNull()
    expect(root.querySelector('[data-track="T1"]')).not.toBeNull()
    expect(root.querySelector('[data-track="A1"]')).not.toBeNull()

    const clipA = root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_A}"]`)
    const clipB = root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_B}"]`)
    const clipC = root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_NO_CONTEXT}"]`)
    expect(clipA).not.toBeNull()
    expect(clipB).not.toBeNull()
    expect(clipC).not.toBeNull()

    expect(px(clipA?.style.left ?? '') / px(clipA?.style.width ?? '')).toBeCloseTo(0.5, 6)
    expect(px(clipB?.style.left ?? '') / px(clipB?.style.width ?? '')).toBeCloseTo(2.5, 6)
    expect(px(clipA?.style.width ?? '') / px(clipC?.style.width ?? '')).toBeCloseTo(2, 6)

    expect(clipA?.textContent).toContain('source-a')
    expect(clipA?.textContent).toContain('0:02.0')
    expect(root.querySelector('[data-timeline-ruler]')).not.toBeNull()
    expect(root.querySelector('[data-playhead]')).not.toBeNull()

    dispose()
  })

  it('clicking a clip reuses selection and switches candidate context by clip start beat', async () => {
    const { root, dispose } = await mountWorkspace()

    root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_B}"]`)?.click()

    await vi.waitFor(() => expect(root.textContent).toContain('B-CANDIDATE'))
    expect(root.textContent).not.toContain('A-CANDIDATE')
    expect(root.querySelector(`[data-clip-id="${CLIP_B}"]`)?.classList.contains('finecut-selected')).toBe(true)
    expect(root.querySelector(`[data-selected-context="${CONTEXT_B}"]`)).not.toBeNull()

    dispose()
  })

  it('clears candidate context when no narration segment contains the clip start', async () => {
    const { root, dispose, fetchMock } = await mountWorkspace()

    root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_B}"]`)?.click()
    await vi.waitFor(() => expect(root.textContent).toContain('B-CANDIDATE'))
    const callsBefore = candidateCalls(fetchMock)

    root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_NO_CONTEXT}"]`)?.click()

    expect(root.querySelector('[data-selected-context]')).toBeNull()
    expect(root.textContent).not.toContain('A-CANDIDATE')
    expect(root.textContent).not.toContain('B-CANDIDATE')
    expect(candidateCalls(fetchMock)).toEqual(callsBefore)
    expect(root.querySelector(`[data-clip-id="${CLIP_NO_CONTEXT}"]`)?.classList.contains('finecut-selected')).toBe(true)

    dispose()
  })

  it('moves the playhead when the visual timeline is clicked', async () => {
    const { root, dispose } = await mountWorkspace()
    const surface = root.querySelector<HTMLElement>('[data-timeline-surface]')
    expect(surface).not.toBeNull()
    if (!surface) return

    const pixelsPerSecond = Number(surface.dataset.pixelsPerSecond)
    expect(pixelsPerSecond).toBeGreaterThan(0)
    surface.getBoundingClientRect = () => ({
      x: 10,
      y: 0,
      left: 10,
      top: 0,
      right: 10 + pixelsPerSecond * 10,
      bottom: 160,
      width: pixelsPerSecond * 10,
      height: 160,
      toJSON: () => ({}),
    })

    surface.dispatchEvent(new MouseEvent('click', {
      bubbles: true,
      clientX: 10 + pixelsPerSecond * 4.25,
      clientY: 20,
    }))

    const playhead = root.querySelector<HTMLElement>('[data-playhead]')
    expect(px(playhead?.style.left ?? '')).toBeCloseTo(pixelsPerSecond * 4.25, 4)
    expect(root.textContent).toContain('预览位置 0:04.3')

    dispose()
  })

  it('supports dragging the playhead as UI-only time state', async () => {
    const { root, dispose } = await mountWorkspace()
    const surface = root.querySelector<HTMLElement>('[data-timeline-surface]')
    const playhead = root.querySelector<HTMLElement>('[data-playhead]')
    expect(surface).not.toBeNull()
    expect(playhead).not.toBeNull()
    if (!surface || !playhead) return

    const pixelsPerSecond = Number(surface.dataset.pixelsPerSecond)
    surface.getBoundingClientRect = () => ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: pixelsPerSecond * 10,
      bottom: 160,
      width: pixelsPerSecond * 10,
      height: 160,
      toJSON: () => ({}),
    })

    playhead.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: pixelsPerSecond }))
    window.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: pixelsPerSecond * 7 }))
    window.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, clientX: pixelsPerSecond * 7 }))

    expect(px(root.querySelector<HTMLElement>('[data-playhead]')?.style.left ?? ''))
      .toBeCloseTo(pixelsPerSecond * 7, 4)
    expect(root.textContent).toContain('预览位置 0:07.0')

    dispose()
  })

  it('zooms the timeline without changing clip relative time relationships', async () => {
    const { root, dispose } = await mountWorkspace()
    const beforeSurface = root.querySelector<HTMLElement>('[data-timeline-surface]')
    const beforeA = root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_A}"]`)
    const beforeB = root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_B}"]`)
    expect(beforeSurface).not.toBeNull()
    expect(beforeA).not.toBeNull()
    expect(beforeB).not.toBeNull()

    const beforeScale = Number(beforeSurface?.dataset.pixelsPerSecond)
    const beforeALeft = px(beforeA?.style.left ?? '')
    const beforeAWidth = px(beforeA?.style.width ?? '')
    const beforeBLeft = px(beforeB?.style.left ?? '')

    const zoomIn = root.querySelector<HTMLButtonElement>('[aria-label="放大时间线"]')
    expect(zoomIn).not.toBeNull()
    zoomIn?.click()

    const afterSurface = root.querySelector<HTMLElement>('[data-timeline-surface]')
    const afterA = root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_A}"]`)
    const afterB = root.querySelector<HTMLElement>(`[data-clip-id="${CLIP_B}"]`)
    const afterScale = Number(afterSurface?.dataset.pixelsPerSecond)
    expect(afterScale).toBeGreaterThan(beforeScale)

    const scaleFactor = afterScale / beforeScale
    expect(px(afterA?.style.left ?? '') / beforeALeft).toBeCloseTo(scaleFactor, 6)
    expect(px(afterA?.style.width ?? '') / beforeAWidth).toBeCloseTo(scaleFactor, 6)
    expect(px(afterB?.style.left ?? '') / beforeBLeft).toBeCloseTo(scaleFactor, 6)
    expect(px(afterB?.style.left ?? '') / px(afterA?.style.left ?? '')).toBeCloseTo(5, 6)

    dispose()
  })
})
