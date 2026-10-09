import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountFineCut } from '../src/index'

const PLAN_ID = '11111111-1111-1111-1111-111111111111'
const CONTEXT_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const CONTEXT_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
const CLIP_ID = '44444444-4444-4444-4444-444444444444'
const MEDIA_ID = '66666666-6666-6666-6666-666666666666'
const UNAVAILABLE_MEDIA_ID = '77777777-7777-7777-7777-777777777777'

const timeline = {
  version: 1,
  project_id: '22222222-2222-2222-2222-222222222222',
  source_plan_id: PLAN_ID,
  width: 1920,
  height: 1080,
  fps: 30,
  duration_ms: 10000,
  tracks: [
    {
      id: '33333333-3333-3333-3333-333333333333',
      kind: 'video',
      clips: [
        {
          id: CLIP_ID,
          source_id: 'segment-a',
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
      ],
    },
  ],
}

const narration = {
  track_id: '55555555-5555-5555-5555-555555555555',
  revision: 1,
  audio_uri: 'D:/audio/narration.wav',
  duration_ms: 10000,
  segments: [
    { id: CONTEXT_A, text: '句子 A', start_ms: 0, end_ms: 5000 },
    { id: CONTEXT_B, text: '句子 B', start_ms: 5000, end_ms: 10000 },
  ],
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function candidate(
  contextId: string,
  label: string,
  displayLevel: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    requirement_id: `${contextId}-${label}`,
    sentence_id: contextId,
    source_quote: label,
    importance: 'S',
    candidate_type: 'window',
    candidate_id: null,
    media_id: MEDIA_ID,
    source_in_ms: 1000,
    source_out_ms: 7000,
    anchor_in_ms: 1400,
    anchor_out_ms: 1800,
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
    ...overrides,
  }
}

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function installFetch(options: { exportError?: string } = {}) {
  let savedTimeline = clone(timeline)
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
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_A}`)) {
      return response({
        context_id: CONTEXT_A,
        items: [
          candidate(CONTEXT_A, 'DIRECT', 'S'),
          candidate(CONTEXT_A, 'SUPPORT', 'A'),
          candidate(CONTEXT_A, 'SHORT', 'A', { source_in_ms: 1000, source_out_ms: 4000 }),
          candidate(CONTEXT_A, 'RELATED', 'B'),
          candidate(CONTEXT_A, 'UNAVAILABLE', 'B', { media_id: UNAVAILABLE_MEDIA_ID }),
          candidate(CONTEXT_A, 'GENERIC', 'Generic'),
          candidate(CONTEXT_A, 'SOURCE', 'Fallback/Source'),
          candidate(CONTEXT_A, 'REUSE', 'Fallback/Reuse'),
          candidate(CONTEXT_A, 'UNKNOWN', 'UNKNOWN'),
          candidate(CONTEXT_A, 'REJECT', 'REJECT'),
          candidate(CONTEXT_A, 'blocked', 'S', { pollution_level: 'blocked' }),
          candidate(CONTEXT_A, 'illegal', 'A', { source_in_ms: 4000, source_out_ms: 3000 }),
        ],
      })
    }
    if (url.endsWith(`/finecut/plans/${PLAN_ID}/candidates/${CONTEXT_B}`)) {
      return response({ context_id: CONTEXT_B, items: [candidate(CONTEXT_B, 'B-DIRECT', 'S')] })
    }
    if (url.endsWith(`/finecut/media/${MEDIA_ID}`)) {
      return response({ media_id: MEDIA_ID, source_uri: 'D:/media/replacement.mp4' })
    }
    if (url.endsWith(`/finecut/media/${UNAVAILABLE_MEDIA_ID}`)) {
      return response({ detail: 'FineCut media not found' }, 404)
    }
    if (url.endsWith('/finecut/edit/replace') && method === 'POST') {
      const body = JSON.parse(String(init?.body))
      const document = clone(body.document)
      const clip = document.tracks.flatMap((track: typeof timeline.tracks[number]) => track.clips)
        .find((item: typeof timeline.tracks[number]['clips'][number]) => item.id === body.target_clip_id)
      if (!clip || body.candidate.source_out_ms - body.candidate.source_in_ms < clip.duration_ms) {
        return response({ detail: 'candidate duration is shorter than timeline slot' }, 400)
      }
      clip.source_id = body.candidate.media_id
      clip.source_path = body.media.source_uri
      clip.source_in_ms = body.candidate.source_in_ms
      clip.source_out_ms = body.candidate.source_in_ms + clip.duration_ms
      return response(document)
    }
    if (url.endsWith('/exports/jianying') && method === 'POST') {
      if (options.exportError) {
        return response({ error: { message: options.exportError } }, 409)
      }
      return response({
        draft_name: 'E2E验收项目',
        output_path: 'D:/Jianying/Drafts/E2E验收项目',
      })
    }
    return new Response('not found', { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return {
    fetchMock,
    getSavedTimeline: () => clone(savedTimeline),
  }
}

function findCard(root: HTMLElement, label: string): HTMLElement {
  const card = Array.from(root.querySelectorAll<HTMLElement>('.finecut-card'))
    .find((item) => item.textContent?.includes(label))
  if (!card) throw new Error(`candidate card not found: ${label}`)
  return card
}

function findButton(root: HTMLElement, label: string): HTMLButtonElement {
  const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
    .find((item) => item.textContent === label)
  if (!button) throw new Error(`button not found: ${label}`)
  return button
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.replaceChildren()
})

describe('FineCut workspace', () => {
  it('saves the editing draft before exporting it to Jianying', async () => {
    const { fetchMock } = installFetch()
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })

    await vi.waitFor(() => expect(
      root.querySelector<HTMLButtonElement>('[data-export-jianying]')?.disabled,
    ).toBe(false))
    expect(root.textContent).toContain('ClipAtlas 剪辑草稿')
    expect(root.textContent).not.toContain('外部工程')
    root.querySelector<HTMLButtonElement>('[data-export-jianying]')?.click()
    await vi.waitFor(() => expect(root.textContent).toContain('D:/Jianying/Drafts/E2E验收项目'))

    const calls = fetchMock.mock.calls.map(([input, init]) => ({
      url: String(input),
      method: init?.method ?? 'GET',
    }))
    const saveIndex = calls.findIndex((call) =>
      call.method === 'PUT' && call.url.endsWith('/finecut/plans/' + PLAN_ID + '/timeline'))
    const exportIndex = calls.findIndex((call) =>
      call.method === 'POST' && call.url.endsWith('/exports/jianying'))
    expect(saveIndex).toBeGreaterThanOrEqual(0)
    expect(exportIndex).toBeGreaterThan(saveIndex)
    dispose()
  })

  it('shows the backend reason when Jianying export fails', async () => {
    installFetch({ exportError: '剪映草稿目录不可写' })
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })

    await vi.waitFor(() => expect(
      root.querySelector<HTMLButtonElement>('[data-export-jianying]')?.disabled,
    ).toBe(false))
    root.querySelector<HTMLButtonElement>('[data-export-jianying]')?.click()

    await vi.waitFor(() => expect(root.textContent).toContain('剪映草稿目录不可写'))
    dispose()
  })

  it('shows only the selected narration context and switches immediately from A to B', async () => {
    installFetch()
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })

    await vi.waitFor(() => expect(root.textContent).toContain('DIRECT'))
    expect(root.textContent).not.toContain('B-DIRECT')
    expect(root.querySelector(`[data-selected-context="${CONTEXT_A}"]`)).not.toBeNull()

    const segmentB = root.querySelector<HTMLButtonElement>(`[data-context-id="${CONTEXT_B}"]`)
    expect(segmentB).not.toBeNull()
    segmentB?.click()

    await vi.waitFor(() => expect(root.textContent).toContain('B-DIRECT'))
    expect(root.textContent).not.toContain('SUPPORT')
    expect(root.textContent).not.toContain('RELATED')
    expect(root.textContent).not.toContain('GENERIC')
    expect(root.textContent).not.toContain('SOURCE')
    expect(root.textContent).not.toContain('REUSE')
    expect(root.querySelector(`[data-selected-context="${CONTEXT_B}"]`)).not.toBeNull()
    expect(root.querySelector(`[data-selected-context="${CONTEXT_A}"]`)).toBeNull()

    dispose()
  })

  it('groups DIRECT/SUPPORT/RELATED/GENERIC and keeps SOURCE/REUSE only in fallback', async () => {
    installFetch()
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })

    await vi.waitFor(() => expect(root.textContent).toContain('DIRECT'))

    expect(root.querySelector('[data-candidate-section="S"]')?.textContent).toContain('DIRECT')
    expect(root.querySelector('[data-candidate-section="A"]')?.textContent).toContain('SUPPORT')
    expect(root.querySelector('[data-candidate-section="B"]')?.textContent).toContain('RELATED')
    expect(root.querySelector('[data-candidate-section="Generic"]')?.textContent).toContain('GENERIC')

    const normalSections = Array.from(root.querySelectorAll('[data-candidate-section="S"], [data-candidate-section="A"], [data-candidate-section="B"], [data-candidate-section="Generic"]'))
      .map((node) => node.textContent ?? '')
      .join(' ')
    expect(normalSections).not.toContain('SOURCE')
    expect(normalSections).not.toContain('REUSE')

    const fallback = root.querySelector<HTMLDetailsElement>('[data-candidate-section="fallback"]')
    expect(fallback).not.toBeNull()
    expect(fallback?.open).toBe(false)
    expect(fallback?.textContent).toContain('SOURCE')
    expect(fallback?.textContent).toContain('REUSE')

    expect(root.textContent).not.toContain('UNKNOWN')
    expect(root.textContent).not.toContain('REJECT')
    expect(root.textContent).not.toContain('blocked')
    expect(root.textContent).not.toContain('illegal')

    dispose()
  })

  it('highlights the current narration segment and selected V1 clip', async () => {
    installFetch()
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })

    await vi.waitFor(() => expect(root.querySelector(`[data-selected-context="${CONTEXT_A}"]`)).not.toBeNull())
    const segmentA = root.querySelector<HTMLElement>(`[data-context-id="${CONTEXT_A}"]`)
    expect(segmentA?.classList.contains('finecut-selected')).toBe(true)

    const clip = root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_ID}"]`)
    expect(clip).not.toBeNull()
    expect(clip?.classList.contains('finecut-selected')).toBe(false)
    clip?.click()
    expect(root.querySelector(`[data-clip-id="${CLIP_ID}"]`)?.classList.contains('finecut-selected')).toBe(true)

    dispose()
  })

  it('replaces the selected clip and supports undo redo with session snapshots', async () => {
    const harness = installFetch()
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })

    await vi.waitFor(() => expect(root.textContent).toContain('DIRECT'))
    root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_ID}"]`)?.click()

    const direct = findCard(root, 'DIRECT')
    const replace = Array.from(direct.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent === '替换当前镜头')
    expect(replace?.disabled).toBe(false)
    replace?.click()

    await vi.waitFor(() => {
      const calls = harness.fetchMock.mock.calls.filter(([input, init]) =>
        String(input).endsWith('/finecut/edit/replace') && init?.method === 'POST')
      expect(calls).toHaveLength(1)
    })
    await vi.waitFor(() => expect(findButton(root, '撤销').disabled).toBe(false))
    expect(root.textContent).toContain('句子 A')

    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips[0].source_path)
      .toBe('D:/media/replacement.mp4'))
    await vi.waitFor(() => expect(findButton(root, '保存').disabled).toBe(false))

    findButton(root, '撤销').click()
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips[0].source_path)
      .toBe('D:/media/a.mp4'))
    await vi.waitFor(() => expect(findButton(root, '保存').disabled).toBe(false))

    findButton(root, '重做').click()
    findButton(root, '保存').click()
    await vi.waitFor(() => expect(harness.getSavedTimeline().tracks[0].clips[0].source_path)
      .toBe('D:/media/replacement.mp4'))

    dispose()
  })

  it('keeps a short candidate visible but disables replace and drag', async () => {
    installFetch()
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })

    await vi.waitFor(() => expect(root.textContent).toContain('SHORT'))
    root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_ID}"]`)?.click()

    const short = findCard(root, 'SHORT')
    expect(short.textContent).toContain('时长不足')
    expect(short.draggable).toBe(false)
    const replace = Array.from(short.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent === '替换当前镜头')
    expect(replace?.disabled).toBe(true)

    dispose()
  })

  it('disables replace when MediaReference is unavailable', async () => {
    installFetch()
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })

    await vi.waitFor(() => expect(root.textContent).toContain('UNAVAILABLE'))
    root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_ID}"]`)?.click()

    const unavailable = findCard(root, 'UNAVAILABLE')
    expect(unavailable.textContent).toContain('素材不可用')
    const replace = Array.from(unavailable.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent === '替换当前镜头')
    expect(replace?.disabled).toBe(true)

    dispose()
  })

  it('uses the same replace endpoint when a candidate is dropped onto the selected V1 clip', async () => {
    const harness = installFetch()
    const root = document.createElement('div')
    document.body.append(root)
    const dispose = mountFineCut(root, { planId: PLAN_ID })

    await vi.waitFor(() => expect(root.textContent).toContain('DIRECT'))
    const clip = root.querySelector<HTMLButtonElement>(`[data-clip-id="${CLIP_ID}"]`)
    clip?.click()
    const direct = findCard(root, 'DIRECT')
    expect(direct.draggable).toBe(true)

    direct.dispatchEvent(new Event('dragstart', { bubbles: true }))
    clip?.dispatchEvent(new Event('dragover', { bubbles: true, cancelable: true }))
    clip?.dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }))

    await vi.waitFor(() => {
      const calls = harness.fetchMock.mock.calls.filter(([input, init]) =>
        String(input).endsWith('/finecut/edit/replace') && init?.method === 'POST')
      expect(calls).toHaveLength(1)
    })

    dispose()
  })
})
