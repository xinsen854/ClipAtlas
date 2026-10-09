import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as rulesApi from '../../api/rules'
import { useAppStore } from '../../stores/useAppStore'
import { RulesPage } from './RulesPage'

vi.mock('../../api/rules', async () => {
  const actual = await vi.importActual<typeof import('../../api/rules')>('../../api/rules')
  return {
    ...actual,
    analyzeProjectRules: vi.fn(),
    previewProjectRules: vi.fn(),
    saveProjectRuleDraft: vi.fn(),
    listProjectRulePacks: vi.fn(),
    getActiveProjectRulePack: vi.fn(),
    activateProjectRulePack: vi.fn(),
  }
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RulesPage />
        </MemoryRouter>
      </QueryClientProvider>
    </AntdApp>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  useAppStore.setState({ currentProjectId: 'project-1' })
  vi.mocked(rulesApi.listProjectRulePacks).mockResolvedValue([])
})

describe('RulesPage', () => {
  it('requires a current project before loading or analyzing project rules', async () => {
    useAppStore.setState({ currentProjectId: null })
    renderPage()

    expect(await screen.findByText('请先选择或创建项目')).toBeInTheDocument()
    expect(rulesApi.listProjectRulePacks).not.toHaveBeenCalled()
    expect(rulesApi.analyzeProjectRules).not.toHaveBeenCalled()
  })

  it('analyzes natural-language instructions and allows candidate rules to be edited', async () => {
    vi.mocked(rulesApi.analyzeProjectRules).mockResolvedValue({
      source_text: 'Model 700 should be read as Model seven hundred.',
      rules: [
        {
          kind: 'pronunciation',
          match: 'Model 700',
          replacement: 'Model seven hundred',
          enabled: true,
        },
      ],
    })
    renderPage()

    fireEvent.change(await screen.findByLabelText('本批规则说明'), {
      target: { value: 'Model 700 should be read as Model seven hundred.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'AI 分析规则' }))

    expect(await screen.findByDisplayValue('Model 700')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Model seven hundred')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('规则 1 替换内容'), {
      target: { value: 'Model seven zero zero' },
    })

    expect(screen.getByLabelText('规则 1 替换内容')).toHaveValue('Model seven zero zero')
    expect(rulesApi.analyzeProjectRules).toHaveBeenCalledWith(
      'project-1',
      'Model 700 should be read as Model seven hundred.',
    )
  })

  it('previews, saves a draft, then explicitly activates the saved revision', async () => {
    const rules: rulesApi.ProjectRule[] = [
      {
        kind: 'speech_suppress',
        match: 'Official Media',
        enabled: true,
      },
    ]
    vi.mocked(rulesApi.analyzeProjectRules).mockResolvedValue({
      source_text: 'Official Media should remain in subtitles but not be spoken.',
      rules,
    })
    vi.mocked(rulesApi.previewProjectRules).mockResolvedValue({
      canonical_text: 'Official Media presents Model 700.',
      speech_text: 'presents Model 700.',
      subtitle_text: 'Official Media presents Model 700.',
      retrieval_text: 'Official Media presents Model 700.',
      semantic_hints: [],
    })
    vi.mocked(rulesApi.saveProjectRuleDraft).mockResolvedValue({
      project_id: 'project-1',
      revision: 1,
      status: 'draft',
      rules,
    })
    vi.mocked(rulesApi.activateProjectRulePack).mockResolvedValue({
      project_id: 'project-1',
      revision: 1,
      status: 'active',
      rules,
    })
    renderPage()

    fireEvent.change(await screen.findByLabelText('本批规则说明'), {
      target: { value: 'Official Media should remain in subtitles but not be spoken.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'AI 分析规则' }))
    await screen.findByDisplayValue('Official Media')

    fireEvent.change(screen.getByLabelText('预览原文'), {
      target: { value: 'Official Media presents Model 700.' },
    })
    fireEvent.click(screen.getByRole('button', { name: '预览效果' }))

    expect(await screen.findByText('presents Model 700.')).toBeInTheDocument()
    expect(screen.getAllByText('Official Media presents Model 700.').length).toBeGreaterThanOrEqual(1)

    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }))

    await waitFor(() => expect(rulesApi.saveProjectRuleDraft).toHaveBeenCalledWith('project-1', rules))
    expect(await screen.findByText('修订 1 · 草稿')).toBeInTheDocument()
    expect(await screen.findByText('草稿已保存')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '激活修订 1' }))

    await waitFor(() => expect(rulesApi.activateProjectRulePack).toHaveBeenCalledWith('project-1', 1))
    expect(await screen.findByText('修订 1 · 当前生效')).toBeInTheDocument()
    expect(await screen.findByText('规则已激活')).toBeInTheDocument()
  }, 10_000)
})
