import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as speechApi from '../../api/speech'
import type {
  ProjectNarrationHistoryResponse,
  SpeechProfile,
  SpeechProviderDescriptor,
} from '../../api/speech'
import { useAppStore } from '../../stores/useAppStore'
import { NarrationPage } from './NarrationPage'

vi.mock('../../api/speech', async () => {
  const actual = await vi.importActual<typeof import('../../api/speech')>('../../api/speech')
  return {
    ...actual,
    listProjectNarrations: vi.fn(),
    listProjectSpeechProfiles: vi.fn(),
    listSpeechProviders: vi.fn(),
    listSpeechVoices: vi.fn(),
    getProjectScript: vi.fn(),
    saveProjectScript: vi.fn(),
  }
})

const provider: SpeechProviderDescriptor = {
  name: 'dashscope',
  model: 'cosyvoice-v3.5-flash',
  capabilities: {
    preset_voices: true,
    voice_metadata: true,
    speed_control: true,
    pitch_control: true,
    volume_control: true,
    emotion_control: true,
    instruction_control: true,
    voice_clone: false,
    voice_design: false,
    word_timestamps: true,
    streaming: false,
    languages: ['zh'],
  },
}

const profile: SpeechProfile = {
  id: 'profile-1',
  project_id: 'project-1',
  provider: 'dashscope',
  model: 'cosyvoice-v3.5-flash',
  voice_id: 'longxiaochun',
  gender_constraint: 'female',
  age_style_constraint: 'young',
  language: 'zh',
  accent: null,
  speed: 1.05,
  pitch: 0,
  volume: 1,
  emotion: '温暖',
  style: '自然',
  instruction: null,
  random_seed: null,
  random_mode: 'none',
  locked: true,
  revision: 2,
  created_at: '2026-09-03T00:00:00Z',
}

const history: ProjectNarrationHistoryResponse = {
  active_track_id: 'track-1',
  tracks: [
    {
      id: 'track-1',
      project_id: 'project-1',
      source_mode: 'tts',
      script_hash: 'hash',
      speech_profile_id: 'profile-1',
      provider: 'dashscope',
      model: 'cosyvoice-v3.5-flash',
      audio_uri: 'data/narration/track-1.wav',
      duration_ms: 83421,
      timing_quality: 'word_exact',
      revision: 3,
      created_at: '2026-09-03T00:00:00Z',
    },
  ],
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NarrationPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  useAppStore.setState({ currentProjectId: 'project-1' })
  vi.mocked(speechApi.listSpeechProviders).mockResolvedValue([provider])
  vi.mocked(speechApi.listProjectSpeechProfiles).mockResolvedValue([profile])
  vi.mocked(speechApi.listProjectNarrations).mockResolvedValue(history)
  vi.mocked(speechApi.listSpeechVoices).mockResolvedValue([])
  vi.mocked(speechApi.getProjectScript).mockResolvedValue({ project_id: 'project-1', text: '', script_hash: '', updated_at: null })
})

describe('NarrationPage', () => {
  it('loads saved text and explicitly saves edits with narration association', async () => {
    vi.mocked(speechApi.getProjectScript).mockResolvedValue({ project_id: 'project-1', text: '已有文案', script_hash: 'old', updated_at: null })
    vi.mocked(speechApi.saveProjectScript).mockResolvedValue({
      script: { project_id: 'project-1', text: '新的真人旁白文案', script_hash: 'new', updated_at: null },
      attached_track_id: 'track-2',
    })
    renderPage()
    await screen.findByDisplayValue('已有文案')
    fireEvent.change(screen.getByLabelText('旁白文案'), { target: { value: '新的真人旁白文案' } })
    fireEvent.click(screen.getByRole('button', { name: '保存文案' }))
    await waitFor(() => expect(speechApi.saveProjectScript).toHaveBeenCalledWith('project-1', '新的真人旁白文案'))
    await screen.findByText(/文案已保存并关联到当前旁白/)
  }, 20_000)
  it('requires a current project before loading project narration state', async () => {
    useAppStore.setState({ currentProjectId: null })
    renderPage()

    expect(await screen.findByText('请先选择或创建项目')).toBeInTheDocument()
    expect(speechApi.listProjectSpeechProfiles).not.toHaveBeenCalled()
    expect(speechApi.listProjectNarrations).not.toHaveBeenCalled()
  })

  it('renders the active narration using backend real duration and localized timing quality', async () => {
    renderPage()

    expect((await screen.findAllByText('01:23.421')).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('词级精确').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('AI 配音').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('修订 3').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('当前使用').length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByRole('button', { name: /激活旁白/ })).not.toBeInTheDocument()
    expect(screen.getAllByText(/longxiaochun/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/已锁定/).length).toBeGreaterThanOrEqual(1)
  })

  it('loads a local txt md or srt file into the existing script field without a backend upload', async () => {
    renderPage()
    await screen.findByText('文案')

    const file = new File(['第一句\n第二句'], '旁白.md', { type: 'text/markdown' })
    Object.defineProperty(file, 'text', {
      value: vi.fn().mockResolvedValue('第一句\n第二句'),
    })

    fireEvent.change(screen.getByLabelText('导入文案文件'), {
      target: { files: [file] },
    })

    await waitFor(() =>
      expect(screen.getByLabelText('旁白文案')).toHaveValue('第一句\n第二句'),
    )
  })

  it('disables AI TTS and explains the missing API even when an old profile remains', async () => {
    vi.mocked(speechApi.listSpeechProviders).mockResolvedValue([])
    renderPage()

    await screen.findByText('文案')
    fireEvent.change(screen.getByLabelText('旁白文案'), {
      target: { value: '测试旁白文案' },
    })

    expect(await screen.findByText('尚未配置 TTS API')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '生成 AI 配音' })).toBeDisabled(),
    )
  })

  it('hides random voice selection when the provider has no preset voices', async () => {
    vi.mocked(speechApi.listSpeechProviders).mockResolvedValue([
      { ...provider, capabilities: { ...provider.capabilities, preset_voices: false, voice_metadata: false } },
    ])
    vi.mocked(speechApi.listProjectSpeechProfiles).mockResolvedValue([])
    renderPage()

    await screen.findByText('选择语音配置')
    expect(screen.queryByRole('button', { name: '随机' })).not.toBeInTheDocument()
  })

  it('opens the upload workflow when the current narration is imported', async () => {
    vi.mocked(speechApi.listProjectNarrations).mockResolvedValue({
      active_track_id: 'track-1',
      tracks: [{ ...history.tracks[0], source_mode: 'imported' }],
    })
    renderPage()

    expect(await screen.findByRole('button', { name: '上传并使用真人旁白' })).toBeInTheDocument()
  })
})
