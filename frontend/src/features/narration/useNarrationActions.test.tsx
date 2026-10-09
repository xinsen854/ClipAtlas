import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as speechApi from '../../api/speech'
import type {
  NarrationTrackResponse,
  SpeechProfile,
} from '../../api/speech'
import { useNarrationActions } from './useNarrationActions'

vi.mock('../../api/speech', async () => {
  const actual = await vi.importActual<typeof import('../../api/speech')>('../../api/speech')
  return {
    ...actual,
    activateNarrationTrack: vi.fn(),
    createSpeechProfile: vi.fn(),
    createTtsNarration: vi.fn(),
    importNarration: vi.fn(),
    randomizeSpeechProfile: vi.fn(),
  }
})

const profile: SpeechProfile = {
  id: 'profile-new',
  project_id: 'project-1',
  provider: 'dashscope',
  model: 'cosyvoice-v3.5-flash',
  voice_id: 'voice-1',
  gender_constraint: 'female',
  age_style_constraint: 'young',
  language: 'zh',
  accent: null,
  speed: 1.1,
  pitch: 0,
  volume: 1,
  emotion: '温暖',
  style: '自然',
  instruction: null,
  random_seed: null,
  random_mode: 'none',
  locked: false,
  revision: 1,
  created_at: '2026-09-03T00:00:00Z',
}

const narration: NarrationTrackResponse = {
  track: {
    id: 'track-1',
    project_id: 'project-1',
    source_mode: 'tts',
    script_hash: 'hash',
    speech_profile_id: 'profile-new',
    provider: 'dashscope',
    model: 'cosyvoice-v3.5-flash',
    audio_uri: 'data/narration/track-1.wav',
    duration_ms: 12000,
    timing_quality: 'word_exact',
    revision: 1,
    created_at: '2026-09-03T00:00:00Z',
  },
  units: [],
  word_timings: [],
}

function wrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(speechApi.createSpeechProfile).mockResolvedValue(profile)
  vi.mocked(speechApi.randomizeSpeechProfile).mockResolvedValue(profile)
  vi.mocked(speechApi.createTtsNarration).mockResolvedValue(narration)
  vi.mocked(speechApi.importNarration).mockResolvedValue({
    ...narration,
    track: { ...narration.track, source_mode: 'imported', speech_profile_id: null },
  })
  vi.mocked(speechApi.activateNarrationTrack).mockResolvedValue(narration)
})

describe('useNarrationActions', () => {
  it('creates TTS with the exact project, script, and selected speech profile', async () => {
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const { result } = renderHook(() => useNarrationActions('project-1'), {
      wrapper: wrapper(queryClient),
    })

    act(() => {
      result.current.createTts.mutate({
        project_id: 'project-1',
        script: '第一句。\n第二句。',
        speech_profile_id: 'profile-new',
      })
    })

    await waitFor(() => expect(result.current.createTts.isSuccess).toBe(true))
    expect(speechApi.createTtsNarration).toHaveBeenCalledWith({
      project_id: 'project-1',
      script: '第一句。\n第二句。',
      speech_profile_id: 'profile-new',
    })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['project', 'project-1', 'narrations'] })
  })

  it('imports a human narration file without changing the script text', async () => {
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const { result } = renderHook(() => useNarrationActions('project-1'), {
      wrapper: wrapper(queryClient),
    })
    const file = new File(['audio'], 'human.wav', { type: 'audio/wav' })

    act(() => {
      result.current.importTrack.mutate({
        projectId: 'project-1',
        script: ' 保留原始空格的旁白 ',
        file,
      })
    })

    await waitFor(() => expect(result.current.importTrack.isSuccess).toBe(true))
    expect(speechApi.importNarration).toHaveBeenCalledWith({
      projectId: 'project-1',
      script: ' 保留原始空格的旁白 ',
      file,
    })
  })

  it('activates a narration track and refreshes project narration state', async () => {
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const { result } = renderHook(() => useNarrationActions('project-1'), {
      wrapper: wrapper(queryClient),
    })

    act(() => result.current.activateTrack.mutate('track-1'))

    await waitFor(() => expect(result.current.activateTrack.isSuccess).toBe(true))
    expect(speechApi.activateNarrationTrack).toHaveBeenCalledWith('track-1')
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['project', 'project-1', 'narrations'] })
  })
})
