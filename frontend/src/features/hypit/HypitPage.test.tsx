import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as hypitApi from '../../api/hypit'
import { HypitPage } from './HypitPage'

vi.mock('../../api/hypit', () => ({
  deleteHypitReference: vi.fn(),
  getHypitBrief: vi.fn(),
  getHypitConfig: vi.fn(),
  getHypitStatus: vi.fn(),
  hypitOutputUrl: vi.fn((buildId: string, output: string) => `/download/${buildId}/${output}`),
  listHypitBuilds: vi.fn(),
  listHypitReferences: vi.fn(),
  listHypitInputs: vi.fn(),
  openHypitOutput: vi.fn(),
  updateHypitConfig: vi.fn(),
  updateHypitBrief: vi.fn(),
  updateHypitBuildTitle: vi.fn(),
  uploadHypitReference: vi.fn(),
  uploadHypitInput: vi.fn(),
  submitHypitBuild: vi.fn(),
  startHypit: vi.fn(),
  stopHypit: vi.fn(),
  testHypitConnection: vi.fn(),
}))

const config: hypitApi.HypitConfig = {
  distribution_root: 'D:/Hypit',
  workspace: 'D:/HypitWorkspace',
  run_file: 'D:/HypitWorkspace/build.svrun',
  endpoint: 'hypihub.default',
  provider_package: '@hypit/provider-hypihub',
  base_url: 'https://hypit.ai',
  base_url_field: 'baseUrl',
  credential_field: 'apiKey',
  provider_config: {},
  api_key_configured: false,
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={client}><HypitPage /></QueryClientProvider>
    </AntdApp>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(hypitApi.getHypitConfig).mockResolvedValue(config)
  vi.mocked(hypitApi.getHypitStatus).mockResolvedValue({
    configured: true,
    running: false,
    url: null,
    pid: null,
    version: '0.1.10',
    commit: '98000342cc222392ac8813cca2f1977c979821a8',
  })
  vi.mocked(hypitApi.listHypitReferences).mockResolvedValue([])
  vi.mocked(hypitApi.listHypitInputs).mockResolvedValue([])
  vi.mocked(hypitApi.getHypitBrief).mockResolvedValue({ text: '' })
  vi.mocked(hypitApi.listHypitBuilds).mockResolvedValue([])
  vi.mocked(hypitApi.submitHypitBuild).mockResolvedValue({})
  vi.mocked(hypitApi.testHypitConnection).mockResolvedValue({ ok: true, message: '连接成功，API Key 可用。' })
  vi.mocked(hypitApi.updateHypitConfig).mockImplementation(async (input) => ({
    ...config,
    ...input,
    api_key_configured: Boolean(input.api_key),
  }))
})

describe('HypitPage', () => {
  it('keeps official and third-party entries while configuring WaveSpeed with a preset', async () => {
    renderPage()

    expect(await screen.findByText('1. 导入对标视频')).toBeInTheDocument()
    await screen.findByText('Hypit 官方')
    expect(screen.getByText(/可模仿的镜头、风格或运动/)).toBeInTheDocument()
    expect(screen.getByText('2. 替换素材')).toBeInTheDocument()
    expect(screen.getByLabelText('模仿要求')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '替换产品' })).toBeInTheDocument()
    expect(screen.getByText('4. 模型与费用')).toBeInTheDocument()
    expect(screen.getByText('Hypit 开源来源')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'GitHub hypit-ai/hypit' })).toHaveAttribute(
      'href',
      'https://github.com/hypit-ai/hypit',
    )
    expect(screen.queryByLabelText('Hypit 发行目录')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Provider 包')).not.toBeInTheDocument()
    fireEvent.mouseDown(screen.getByLabelText('接入类型'))
    fireEvent.click(await screen.findByText('第三方 API'))
    expect(await screen.findByLabelText('第三方服务商')).toBeInTheDocument()
    expect(screen.getByText('WaveSpeed AI')).toBeInTheDocument()
    expect(await screen.findByLabelText('视频模型')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByLabelText('视频模型'))
    fireEvent.click(await screen.findByText('Seedance 2.5'))
    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'private-key' } })
    fireEvent.click(screen.getByRole('button', { name: '保存模型服务' }))

    await waitFor(() => expect(hypitApi.updateHypitConfig).toHaveBeenCalledTimes(1))
    expect(vi.mocked(hypitApi.updateHypitConfig).mock.calls[0]?.[0]).toMatchObject({
      endpoint: 'wavespeed.default',
      provider_package: '@hypit/provider-wavespeed',
      base_url: 'https://api.wavespeed.ai/api/v3',
      provider_config: { selectedModel: 'seedance-2.5', pollIntervalMs: 5000 },
      api_key: 'private-key',
    })
    expect(screen.queryByLabelText('Provider 包')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('服务名称')).not.toBeInTheDocument()
  }, 30_000)

  it('tests an unsaved WaveSpeed key without exposing runtime settings', async () => {
    renderPage()

    await screen.findByText('Hypit 官方')
    fireEvent.mouseDown(screen.getByLabelText('接入类型'))
    fireEvent.click(await screen.findByText('第三方 API'))
    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'private-key' } })
    fireEvent.click(screen.getByRole('button', { name: '测试连接' }))

    await waitFor(() => expect(hypitApi.testHypitConnection).toHaveBeenCalledTimes(1))
    expect(vi.mocked(hypitApi.testHypitConnection).mock.calls[0]?.[0]).toEqual({
      api_key: 'private-key',
      provider_package: '@hypit/provider-wavespeed',
      base_url: 'https://api.wavespeed.ai/api/v3',
    })
    expect(await screen.findByText('连接成功，API Key 可用。')).toBeInTheDocument()
  })

  it('reveals provider details only for another third-party adapter', async () => {
    renderPage()

    await screen.findByText('Hypit 官方')
    expect(screen.queryByLabelText('Provider 包')).not.toBeInTheDocument()
    fireEvent.mouseDown(screen.getByLabelText('接入类型'))
    fireEvent.click(await screen.findByText('第三方 API'))
    fireEvent.mouseDown(screen.getByLabelText('第三方服务商'))
    fireEvent.click(await screen.findByText('其他 Hypit Provider'))

    expect(await screen.findByLabelText('Provider 包')).toBeInTheDocument()
    expect(screen.getByLabelText('端点名称')).toBeInTheDocument()
    expect(screen.getByLabelText('API 地址')).toBeInTheDocument()
    expect(screen.getByText(/不同视频 API 协议不通用/)).toBeInTheDocument()
  })

  it('shows imported references and completed work with export', async () => {
    vi.mocked(hypitApi.listHypitReferences).mockResolvedValue([
      { name: 'reference.mp4', size: 2048, modified_at: '2026-09-17T00:00:00Z' },
    ])
    vi.mocked(hypitApi.listHypitBuilds).mockResolvedValue([
      {
        id: 'build-1',
        created_at: '2026-09-17T00:00:00Z',
        title: '对标短片',
        outcome: 'complete',
        targets: ['final.video'],
        output_count: 1,
      },
    ])
    renderPage()

    expect(await screen.findByText('reference.mp4')).toBeInTheDocument()
    expect(await screen.findByDisplayValue('对标短片')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /打开成片/ }))
    await waitFor(() => expect(hypitApi.openHypitOutput).toHaveBeenCalledWith(
      'build-1',
      'final.video',
    ))
  })

  it('shows the running Studio inside the independent module', async () => {
    vi.mocked(hypitApi.getHypitStatus).mockResolvedValue({
      configured: true,
      running: true,
      url: 'http://127.0.0.1:5179',
      pid: 123,
      version: '0.1.10',
      commit: '98000342cc222392ac8813cca2f1977c979821a8',
    })
    renderPage()

    const studio = await screen.findByTitle('Hypit Studio')
    expect(studio).toHaveAttribute('src', 'http://127.0.0.1:5179')
    expect(screen.getByText('运行中')).toBeInTheDocument()
  })
})
