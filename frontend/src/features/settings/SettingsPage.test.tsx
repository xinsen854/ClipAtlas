import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as settingsApi from '../../api/settings'
import * as libraryApi from '../../api/library'
import type { PublicSettings } from '../../api/settings'
import { router } from '../../app/router'

vi.mock('../../api/settings', async () => {
  const actual = await vi.importActual<typeof import('../../api/settings')>('../../api/settings')
  return {
    ...actual,
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
    testSettingsConnection: vi.fn(),
    detectBailianModels: vi.fn(),
  }
})

vi.mock('../../api/library',async()=>({
  ...await vi.importActual<typeof import('../../api/library')>('../../api/library'),
  getCacheLocation:vi.fn(),moveCacheLocation:vi.fn(),
}))

const settings: PublicSettings = {
  library_provider: { value: 'qwen', source: 'file' },
  bailian_base_url: {
    value: 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
    source: 'environment',
  },
  qwen_base_url: { value: 'https://shu26.cfd/v1', source: 'file' },
  qwen_default_model: { value: 'qwen3.8-flash', source: 'default' },
  qwen_long_context_model: { value: 'qwen3.8-flash', source: 'default' },
  embedding_base_url: {
    value: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    source: 'file',
  },
  embedding_model: { value: 'text-embedding-v4', source: 'file' },
  embedding_dimensions: { value: 1024, source: 'file' },
  speech_provider: { value: 'dashscope', source: 'file' },
  speech_base_url: {
    value: 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer',
    source: 'default',
  },
  speech_model: { value: 'cosyvoice-v3.5-flash', source: 'file' },
  jianying_draft_root: { value: 'D:/JianyingDrafts', source: 'file' },
  jianying_install_dir: { value: 'C:/Program Files/JianyingPro', source: 'file' },
  jianying_user_data: { value: null, source: 'default' },
  jianying_mode: { value: 'portable', source: 'default' },
  jianying_executable: { value: null, source: 'default' },
  bailian_api_key_configured: true,
  bailian_api_key_source: 'environment',
  qwen_api_key_configured: true,
  qwen_api_key_source: 'file',
  embedding_api_key_configured: true,
  embedding_api_key_source: 'file',
  speech_api_key_configured: false,
  speech_api_key_source: 'default',
}

function renderSettingsRoute() {
  const settingsRoute = router.routes[0]?.children?.find((route) => route.path === 'settings')
  if (!settingsRoute?.element) throw new Error('settings route is missing')

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })

  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>{settingsRoute.element}</QueryClientProvider>
    </AntdApp>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(libraryApi.getCacheLocation).mockResolvedValue({path:'D:/cache',restart_required:false,environment_managed:false})
  vi.mocked(settingsApi.getSettings).mockResolvedValue(settings)
  vi.mocked(settingsApi.updateSettings).mockResolvedValue({
    settings,
    restart_required: true,
  })
  vi.mocked(settingsApi.testSettingsConnection).mockResolvedValue({
    ok: true,
    code: 'ok',
    message: '连接成功。',
  })
  vi.mocked(settingsApi.detectBailianModels).mockResolvedValue({
    ok: true,
    code: 'ok',
    message: '模型目录读取成功。',
    models: {
      video_embedding: 'available',
      video_understanding: 'available',
      ocr: 'unavailable',
      asr: 'available',
      media_type: 'available',
      director: 'available',
    },
  })
})

describe('SettingsPage', () => {
  it('renders one Bailian card plus speech and Jianying without refilling secrets', async () => {
    renderSettingsRoute()

    expect(await screen.findByText('阿里云百炼')).toBeInTheDocument()
    expect(screen.getByText('语音服务')).toBeInTheDocument()
    expect(screen.getByText('剪映')).toBeInTheDocument()

    expect(screen.getByLabelText('百炼 API Key')).toHaveValue('')
    expect(screen.getByLabelText('语音 API Key')).toHaveValue('')
    expect(screen.queryByLabelText('视频理解 API Key')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('语义索引 API Key')).not.toBeInTheDocument()
  })

  it('visually separates the unified groups and keeps Jianying field guidance', async () => {
    renderSettingsRoute()

    await screen.findByText('阿里云百炼')
    expect(screen.getByTestId('settings-section-bailian')).toHaveStyle({ background: '#f7f3ff' })
    expect(screen.getByTestId('settings-section-speech')).toHaveStyle({ background: '#eff8f7' })
    expect(screen.getByTestId('settings-section-jianying')).toHaveStyle({ background: '#f6f2ed' })

    expect(
      screen.getByText(
        '填写 aliyuncs.com 的 Workspace 地址；软件会自动派生 compatible-mode/v1 与 api/v1。',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('只填写剪映安装文件夹，不要填写 exe 或启动参数。')).toBeInTheDocument()
    expect(screen.getByText('只填写剪映 .exe 文件路径，不要附加 --src1 等启动参数。')).toBeInTheDocument()
    expect(screen.getByText('Portable 草稿可留空；剪映专业版 10.8 接线时再填写。')).toBeInTheDocument()
  })

  it('shows the environment ownership warning for Bailian environment settings', async () => {
    renderSettingsRoute()

    expect(
      await screen.findAllByText('由环境变量管理；本机配置不会覆盖当前环境变量。'),
    ).not.toHaveLength(0)
  })

  it('checks the Bailian models (incl. media-type and director) with an unsaved key', async () => {
    renderSettingsRoute()

    await screen.findByText('阿里云百炼')
    fireEvent.change(screen.getByLabelText('百炼 API Key'), {
      target: { value: 'typed-bailian-key' },
    })
    fireEvent.click(screen.getByRole('button', { name: '检查模型' }))

    await waitFor(() => expect(settingsApi.detectBailianModels).toHaveBeenCalledTimes(1))
    expect(vi.mocked(settingsApi.detectBailianModels).mock.calls[0]?.[0]).toEqual({
      api_key: 'typed-bailian-key',
      base_url: 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
    })
    expect(settingsApi.updateSettings).not.toHaveBeenCalled()
    expect(await screen.findByText('模型目录读取成功。')).toBeInTheDocument()
    expect(screen.getByText('视频向量 · qwen3-vl-embedding')).toBeInTheDocument()
    expect(screen.getByText('视频理解 · qwen3.8-flash')).toBeInTheDocument()
    expect(screen.getByText('OCR · qwen3.5-ocr')).toBeInTheDocument()
    expect(screen.getByText('ASR · qwen-audio-3.0-asr-flash')).toBeInTheDocument()
    expect(screen.getByText('画面类型标注 · qwen3.8-flash')).toBeInTheDocument()
    expect(screen.getByText('文案解析 · qwen3.8-flash')).toBeInTheDocument()
    expect(screen.getAllByText('✅ 可用')).toHaveLength(5)
    expect(screen.getByText('❌ 不可用')).toBeInTheDocument()
  })

  it('keeps the TTS connection probe on the existing speech configuration', async () => {
    renderSettingsRoute()

    await screen.findByText('语音服务')
    const speechSection = within(screen.getByTestId('settings-section-speech'))
    fireEvent.click(speechSection.getByRole('button', { name: '测试连接' }))

    await waitFor(() => expect(settingsApi.testSettingsConnection).toHaveBeenCalledTimes(1))
    expect(vi.mocked(settingsApi.testSettingsConnection).mock.calls[0]?.[0]).toEqual({
      service: 'speech',
      provider: 'dashscope',
      base_url: 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer',
      model: 'cosyvoice-v3.5-flash',
    })
  })

  it('hides DashScope protocol details from the speech form', async () => {
    renderSettingsRoute()

    await screen.findByText('语音服务')
    const speechSection = within(screen.getByTestId('settings-section-speech'))
    expect(speechSection.queryByLabelText('语音 Provider')).not.toBeInTheDocument()
    expect(speechSection.queryByLabelText('Base URL')).not.toBeInTheDocument()
    expect(speechSection.queryByLabelText('默认模型')).not.toBeInTheDocument()
    expect(speechSection.getByText(/cosyvoice-v3.5-flash/)).toBeInTheDocument()
  })

  it('omits untouched secrets and only sends a newly entered Bailian secret once', async () => {
    renderSettingsRoute()

    await screen.findByText('阿里云百炼')
    const secretInput = screen.getByLabelText('百炼 API Key')
    fireEvent.change(secretInput, { target: { value: 'new-bailian-secret' } })
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))

    await waitFor(() => expect(settingsApi.updateSettings).toHaveBeenCalledTimes(1))
    const firstPayload = vi.mocked(settingsApi.updateSettings).mock.calls[0]?.[0]

    expect(firstPayload).toMatchObject({ bailian_api_key: 'new-bailian-secret' })
    expect(firstPayload).not.toHaveProperty('qwen_api_key')
    expect(firstPayload).not.toHaveProperty('embedding_api_key')
    expect(firstPayload).not.toHaveProperty('speech_api_key')
    expect(await screen.findByText('设置已保存。重启 ClipAtlas 后生效。')).toBeInTheDocument()
    expect(await screen.findByText('设置已保存')).toBeInTheDocument()
    expect(secretInput).toHaveValue('')

    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => expect(settingsApi.updateSettings).toHaveBeenCalledTimes(2))
    expect(vi.mocked(settingsApi.updateSettings).mock.calls[1]?.[0]).not.toHaveProperty(
      'bailian_api_key',
    )
  })

  it('clears a saved Bailian secret only through its clear flag', async () => {
    renderSettingsRoute()

    await screen.findByText('阿里云百炼')
    const bailianSection = within(screen.getByTestId('settings-section-bailian'))
    fireEvent.click(bailianSection.getByRole('button', { name: '清除已保存密钥' }))
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))

    await waitFor(() => expect(settingsApi.updateSettings).toHaveBeenCalledTimes(1))
    const payload = vi.mocked(settingsApi.updateSettings).mock.calls[0]?.[0]
    expect(payload).toMatchObject({ clear_bailian_api_key: true })
    expect(payload).not.toHaveProperty('bailian_api_key')
  })
})
