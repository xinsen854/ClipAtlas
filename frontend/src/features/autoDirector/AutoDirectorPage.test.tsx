import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as autoDirectorApi from '../../api/autoDirector'
import * as roughCutApi from '../../api/roughCut'
import * as speechApi from '../../api/speech'
import { useAppStore } from '../../stores/useAppStore'
import { AutoDirectorPage } from './AutoDirectorPage'
import { DEFAULT_STORY_SKILL } from './defaultStorySkill'

const mocks = vi.hoisted(() => ({ navigate: vi.fn() }))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mocks.navigate }
})

vi.mock('../../api/autoDirector', async () => {
  const actual = await vi.importActual<typeof import('../../api/autoDirector')>('../../api/autoDirector')
  return {
    ...actual,
    getAutoDirectorReadiness: vi.fn(),
    analyzeStory: vi.fn(),
    listStoryOutlines: vi.fn(),
    updateStoryOutline: vi.fn(),
    confirmStoryOutline: vi.fn(),
  }
})

vi.mock('../../api/roughCut', async () => {
  const actual = await vi.importActual<typeof import('../../api/roughCut')>('../../api/roughCut')
  return { ...actual, createRoughCutPlan: vi.fn() }
})

vi.mock('../../api/speech', async () => {
  const actual = await vi.importActual<typeof import('../../api/speech')>('../../api/speech')
  return { ...actual, listProjectSpeechProfiles: vi.fn() }
})

const outline: autoDirectorApi.StoryOutline = {
  id: 'outline-1',
  project_id: 'project-1',
  revision: 1,
  skill_name: 'story.md',
  skill_hash: 'a'.repeat(64),
  summary: '先给出结果，再回到旅程开始。',
  hook_rationale: '死亡结果有素材证据，可作为开场钩子。',
  warnings: [],
  status: 'draft',
  created_at: '2026-09-16T00:00:00Z',
  confirmed_at: null,
  nodes: [
    {
      id: 'node-1',
      order: 0,
      title: '结果前置',
      summary: '猫已经死亡。',
      role: 'hook',
      estimated_duration_ms: 3000,
      evidence: [
        {
          evidence_id: 'asr:sentence-9',
          kind: 'asr',
          video_id: 'video-1',
          segment_id: null,
          start_ms: 9000,
          end_ms: 12000,
          text: '医生说它已经没有生命体征了',
          source_name: 'cat.mp4',
        },
      ],
    },
  ],
}

const profile: speechApi.SpeechProfile = {
  id: 'profile-1',
  project_id: 'project-1',
  provider: 'fake',
  model: 'fake-tts-v0.1',
  voice_id: 'voice-1',
  gender_constraint: null,
  age_style_constraint: null,
  language: 'zh-CN',
  accent: null,
  speed: 1,
  pitch: null,
  volume: null,
  emotion: null,
  style: null,
  instruction: null,
  random_seed: null,
  random_mode: 'none',
  locked: true,
  revision: 1,
  created_at: '2026-09-16T00:00:00Z',
}

const plan = {
  id: 'plan-1',
  project_id: 'project-1',
  narration_track_id: 'track-1',
  narration_revision: 1,
  revision: 1,
  total_duration_ms: 3_000,
  settings: {
    top_k: 12,
    semantic_weight: 0.58,
    action_weight: 0.08,
    scene_weight: 0.08,
    emotion_weight: 0.06,
    duration_weight: 0.12,
    quality_weight: 0.05,
    max_continuity_bonus: 0.03,
    continuity_window_ms: 30_000,
    reuse_penalty_per_use: 0.08,
    max_reuse_penalty: 0.2,
  },
  beats: [],
  clips: [],
  created_at: '2026-09-16T00:02:00Z',
} satisfies roughCutApi.RoughCutPlan

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <AutoDirectorPage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  useAppStore.setState({ currentProjectId: 'project-1' })
  vi.mocked(autoDirectorApi.getAutoDirectorReadiness).mockResolvedValue({
    project_id: 'project-1',
    ready: true,
    video_count: 1,
    evidence_count: 14,
    visual_count: 8,
    asr_count: 4,
    ocr_count: 2,
    warnings: [],
    message: '',
  })
  vi.mocked(autoDirectorApi.listStoryOutlines).mockResolvedValue([])
  vi.mocked(autoDirectorApi.analyzeStory).mockResolvedValue(outline)
  vi.mocked(autoDirectorApi.updateStoryOutline).mockResolvedValue({ ...outline, revision: 2, id: 'outline-2' })
  vi.mocked(autoDirectorApi.confirmStoryOutline).mockResolvedValue({ ...outline, status: 'confirmed', confirmed_at: '2026-09-16T00:01:00Z' })
  vi.mocked(speechApi.listProjectSpeechProfiles).mockResolvedValue([profile])
  vi.mocked(roughCutApi.createRoughCutPlan).mockResolvedValue(plan)
})

describe('AutoDirectorPage', () => {
  it('uses the built-in evidence-first Story Skill without asking for a script or upload', async () => {
    renderPage()

    expect(await screen.findByText('自动编导')).toBeInTheDocument()
    expect(await screen.findByText(/已完成素材 1 个/)).toBeInTheDocument()
    expect(screen.getByText(/证据 14 条/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /上传文案/ })).not.toBeInTheDocument()
    expect(screen.getByText('Evidence First 编导')).toBeInTheDocument()
    expect(screen.getByText('内置 · 默认启用')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '分析故事' }))

    await waitFor(() => {
      expect(autoDirectorApi.analyzeStory).toHaveBeenCalledWith({
        projectId: 'project-1',
        skillName: DEFAULT_STORY_SKILL.name,
        skillContent: DEFAULT_STORY_SKILL.content,
      })
    })
    expect(await screen.findByDisplayValue('结果前置')).toBeInTheDocument()
    expect(screen.getByText('医生说它已经没有生命体征了')).toBeInTheDocument()
  })

  it('replaces the built-in Story Skill with an uploaded file and can restore it', async () => {
    renderPage()
    await screen.findByText('Evidence First 编导')

    const input = screen.getByLabelText('替换为自定义 Story Skill')
    const customSkill = new File(['结果前置\n禁止虚构事实'], 'story.md', { type: 'text/markdown' })
    Object.defineProperty(customSkill, 'text', { value: async () => '结果前置\n禁止虚构事实' })
    fireEvent.change(input, { target: { files: [customSkill] } })

    expect(await screen.findAllByText('story.md')).toHaveLength(2)
    expect(screen.getByText('自定义')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '分析故事' }))
    await waitFor(() => expect(autoDirectorApi.analyzeStory).toHaveBeenCalledWith({
      projectId: 'project-1',
      skillName: 'story.md',
      skillContent: '结果前置\n禁止虚构事实',
    }))

    fireEvent.click(screen.getByRole('button', { name: '恢复内置 Skill' }))
    expect(screen.getByText('Evidence First 编导')).toBeInTheDocument()
    expect(screen.getByText('内置 · 默认启用')).toBeInTheDocument()
  })

  it('keeps evidence immutable while allowing node text edits, deletion order changes, revision save and confirm', async () => {
    vi.mocked(autoDirectorApi.listStoryOutlines).mockResolvedValue([outline])
    renderPage()

    const title = await screen.findByDisplayValue('结果前置')
    fireEvent.change(title, { target: { value: '死亡结果钩子' } })
    fireEvent.click(screen.getByRole('button', { name: '保存故事简纲修订' }))

    await waitFor(() => expect(autoDirectorApi.updateStoryOutline).toHaveBeenCalledTimes(1))
    const request = vi.mocked(autoDirectorApi.updateStoryOutline).mock.calls[0][0]
    expect(request.projectId).toBe('project-1')
    expect(request.nodes[0]).not.toHaveProperty('evidence')

    fireEvent.click(screen.getByRole('button', { name: '确认故事简纲' }))
    await waitFor(() => expect(autoDirectorApi.confirmStoryOutline).toHaveBeenCalled())
  })

  it('executes a confirmed outline with original audio through the existing rough-cut entry', async () => {
    vi.mocked(autoDirectorApi.listStoryOutlines).mockResolvedValue([
      { ...outline, status: 'confirmed', confirmed_at: '2026-09-16T00:01:00Z' },
    ])
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '生成故事粗剪' }))

    await waitFor(() => expect(roughCutApi.createRoughCutPlan).toHaveBeenCalledWith({
      project_id: 'project-1',
      story_outline_id: 'outline-1',
      voice_strategy: 'original_audio',
    }))
    expect(speechApi.listProjectSpeechProfiles).not.toHaveBeenCalled()
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/rough-cut/plan-1'))
  })

  it('uses an existing speech profile when the confirmed outline selects TTS', async () => {
    vi.mocked(autoDirectorApi.listStoryOutlines).mockResolvedValue([
      { ...outline, status: 'confirmed', confirmed_at: '2026-09-16T00:01:00Z' },
    ])
    renderPage()

    fireEvent.click(await screen.findByText('TTS 配音'))
    expect(await screen.findByText('fake · voice-1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '生成故事粗剪' }))

    await waitFor(() => expect(speechApi.listProjectSpeechProfiles).toHaveBeenCalledWith('project-1'))
    await waitFor(() => expect(roughCutApi.createRoughCutPlan).toHaveBeenCalledWith({
      project_id: 'project-1',
      story_outline_id: 'outline-1',
      voice_strategy: 'tts',
      speech_profile_id: 'profile-1',
    }))
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/rough-cut/plan-1'))
  })
})
