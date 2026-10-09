import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as libraryApi from '../../api/library'
import * as roughCutApi from '../../api/roughCut'
import * as speechApi from '../../api/speech'
import { useAppStore } from '../../stores/useAppStore'
import { ApiError } from '../../api/errors'
import { RoughCutPage } from './RoughCutPage'

vi.mock('../../api/library', async () => {
  const actual = await vi.importActual<typeof import('../../api/library')>('../../api/library')
  return { ...actual, getLibraryItems: vi.fn() }
})

vi.mock('../../api/roughCut', async () => {
  const actual = await vi.importActual<typeof import('../../api/roughCut')>('../../api/roughCut')
  return { ...actual, createRoughCutPlan: vi.fn() }
})

vi.mock('../../api/speech', async () => {
  const actual = await vi.importActual<typeof import('../../api/speech')>('../../api/speech')
  return { ...actual, listProjectNarrations: vi.fn(), getNarrationTrack: vi.fn(), getProjectScript: vi.fn() }
})

const activeTrack = {
  id: 'track-1',
  project_id: 'project-1',
  source_mode: 'tts' as const,
  script_hash: 'hash',
  speech_profile_id: 'profile-1',
  provider: 'dashscope',
  model: 'cosyvoice-v3.5-flash',
  audio_uri: 'data/narration/track-1.wav',
  duration_ms: 83421,
  timing_quality: 'word_exact' as const,
  revision: 3,
  created_at: '2026-09-03T00:00:00Z',
}

const completedItem = {
  id: 'item-1',
  root_id: 'root-1',
  source_path: 'D:/素材/雨夜街景.mp4',
  size_bytes: 123,
  mtime_ns: 1,
  fingerprint: 'fp',
  processed_fingerprint: 'fp',
  status: 'COMPLETED' as const,
  video_id: 'video-1',
  attempts: 1,
  last_error: null,
  created_at: '2026-09-03T00:00:00Z',
  updated_at: '2026-09-03T00:00:00Z',
}

const plan: roughCutApi.RoughCutPlan = {
  id: 'plan-1',
  project_id: 'project-1',
  narration_track_id: 'track-1',
  narration_revision: 3,
  revision: 1,
  total_duration_ms: 83421,
  settings: {
    top_k: 12,
    semantic_weight: 0.58,
    action_weight: 0.08,
    scene_weight: 0.08,
    emotion_weight: 0.06,
    duration_weight: 0.12,
    quality_weight: 0.05,
    max_continuity_bonus: 0.03,
    continuity_window_ms: 30000,
    reuse_penalty_per_use: 0.08,
    max_reuse_penalty: 0.2,
  },
  beats: [],
  clips: [],
  created_at: '2026-09-03T00:00:00Z',
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/rough-cut']}>
        <Routes>
          <Route path="/rough-cut" element={<RoughCutPage />} />
          <Route path="/rough-cut/:planId" element={<div>RESULT PAGE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  useAppStore.setState({ currentProjectId: 'project-1' })
  vi.mocked(speechApi.listProjectNarrations).mockResolvedValue({
    active_track_id: 'track-1',
    tracks: [activeTrack],
  })
  vi.mocked(libraryApi.getLibraryItems).mockResolvedValue([completedItem])
  vi.mocked(roughCutApi.createRoughCutPlan).mockResolvedValue(plan)
  vi.mocked(speechApi.getNarrationTrack).mockResolvedValue({ track: activeTrack, script: '当前旁白对应的真实文案', units: [], word_timings: [] })
  vi.mocked(speechApi.getProjectScript).mockResolvedValue({ project_id: 'project-1', text: '当前旁白对应的真实文案', script_hash: 'hash', updated_at: null })
})

describe('RoughCutPage', () => {
  it('keeps generation status and failure beside the button and prevents duplicate submissions', async () => {
    let reject: (error: Error) => void = () => {}
    vi.mocked(roughCutApi.createRoughCutPlan).mockImplementation(() => new Promise((_resolve,rejectPromise) => { reject=rejectPromise }))
    renderPage()
    await screen.findByText('当前旁白对应的真实文案', {}, { timeout: 10_000 })
    const button=screen.getByRole('button',{name:'生成剪辑草稿'})
    await waitFor(()=>expect(button).toBeEnabled())
    fireEvent.click(button)
    await screen.findByRole('status')
    expect(screen.getByText('正在生成剪辑草稿…')).toBeInTheDocument()
    expect(button).toBeDisabled()
    expect(screen.getByRole('spinbutton',{name:'Top-K'})).toBeDisabled()
    fireEvent.click(button)
    expect(roughCutApi.createRoughCutPlan).toHaveBeenCalledTimes(1)
    reject(new ApiError({status:502,code:'provider_invalid_structured_output',technicalMessage:'actions: list_type; request_id=fixture'}))
    await screen.findByText('剪辑草稿生成失败')
    expect(screen.getByTestId('generation-status')).toHaveTextContent('AI 返回的画面分析格式不正确')
    expect(screen.getByTestId('generation-status')).toHaveTextContent('actions: list_type')
    expect(screen.getByRole('button',{name:'重新生成剪辑草稿'})).toBeEnabled()
    expect(screen.queryByText('RESULT PAGE')).not.toBeInTheDocument()
  },20000)
  it('displays narration text and rejects a mismatched saved script', async () => {
    vi.mocked(speechApi.getProjectScript).mockResolvedValue({ project_id: 'project-1', text: '更新的文案', script_hash: 'different', updated_at: null })
    renderPage()
    await screen.findByText('当前旁白对应的真实文案', {}, { timeout: 10_000 })
    await screen.findByText(/已保存文案与当前旁白不一致/)
    expect(screen.getByRole('button', { name: '生成剪辑草稿' })).toBeDisabled()
  })
  it('disables generation when there is no active narration', async () => {
    vi.mocked(speechApi.listProjectNarrations).mockResolvedValue({ active_track_id: null, tracks: [] })
    renderPage()

    expect(await screen.findByText('请先在“文案与旁白”中激活一个旁白')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成剪辑草稿' })).toBeDisabled()
  })

  it('still rejects track-only timing for TTS narration', async () => {
    vi.mocked(speechApi.listProjectNarrations).mockResolvedValue({
      active_track_id: 'track-1',
      tracks: [{ ...activeTrack, timing_quality: 'track_only' }],
    })
    renderPage()

    expect(await screen.findByText(/当前旁白只有总时长/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成剪辑草稿' })).toBeDisabled()
  })

  it('allows imported track-only narration as a coarse whole-track rough cut', async () => {
    vi.mocked(speechApi.listProjectNarrations).mockResolvedValue({
      active_track_id: 'track-1',
      tracks: [
        {
          ...activeTrack,
          source_mode: 'imported',
          timing_quality: 'track_only',
          speech_profile_id: null,
          provider: null,
          model: null,
        },
      ],
    })
    renderPage()

    expect(await screen.findByText(/生成前将自动识别真人旁白/)).toBeInTheDocument()
    const generate = screen.getByRole('button', { name: '生成剪辑草稿' })
    await waitFor(() => expect(generate).toBeEnabled())

    fireEvent.click(generate)

    await waitFor(() =>
      expect(vi.mocked(roughCutApi.createRoughCutPlan).mock.calls[0]?.[0]).toEqual({
        project_id: 'project-1',
        top_k: 12,
      }),
    )
  })

  it('defaults Top-K to 12 and sends no video restriction in all-material mode', async () => {
    renderPage()

    expect(await screen.findByDisplayValue('12')).toBeInTheDocument()
    await screen.findByText('当前旁白对应的真实文案')
    fireEvent.click(screen.getByRole('button', { name: '生成剪辑草稿' }))

    await waitFor(() =>
      expect(vi.mocked(roughCutApi.createRoughCutPlan).mock.calls[0]?.[0]).toEqual({
        project_id: 'project-1',
        top_k: 12,
      }),
    )
    expect(await screen.findByText('RESULT PAGE')).toBeInTheDocument()
  })

  it('sends selected video ids exactly in specified-material mode', async () => {
    renderPage()

    await screen.findByText('展开当前项目素材（1 个视频）')
    fireEvent.click(screen.getByText('展开当前项目素材（1 个视频）'))
    await screen.findByText('雨夜街景.mp4')
    fireEvent.click(screen.getByText('指定素材'))
    fireEvent.click(screen.getByRole('checkbox', { name: /雨夜街景.mp4/ }))
    fireEvent.click(screen.getByRole('button', { name: '生成剪辑草稿' }))

    await waitFor(() =>
      expect(vi.mocked(roughCutApi.createRoughCutPlan).mock.calls[0]?.[0]).toEqual({
        project_id: 'project-1',
        top_k: 12,
        video_ids: ['video-1'],
      }),
    )
  })
})
