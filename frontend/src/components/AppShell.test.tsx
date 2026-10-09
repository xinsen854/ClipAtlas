import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AppShell } from './AppShell'
import { useAppStore } from '../stores/useAppStore'

vi.mock('../api/projects', () => ({
  listProjects: vi.fn().mockResolvedValue([
    {
      id: 'project-a',
      name: '测试项目',
      description: null,
      created_at: '2026-09-03T00:00:00Z',
      updated_at: '2026-09-03T00:00:00Z',
    },
  ]),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
  getProjectDeletionPreview: vi.fn(),
}))

vi.mock('../api/health', () => ({
  getHealth: vi.fn().mockResolvedValue({ status: 'ok', service: 'clipatlas', version: '0.1.0' }),
}))

function renderShell(initialEntry = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>工作台内容</div>} />
            <Route path="rough-cut" element={<div>剪辑草稿入口</div>} />
            <Route path="finecut/:planId" element={<div>FineCut 工作区</div>} />
            <Route path="*" element={<div>测试内容</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  useAppStore.setState({ currentProjectId: null })
})

describe('AppShell', () => {
  it('places rules before material processing in the navigation', async () => {
    renderShell()

    const labels = ['工作台', '本批规则', '素材库', '素材搜索', '文案与旁白', '自动编导', '剪辑草稿', 'Hypit', '设置']
    for (const label of labels) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
    expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual(labels)
  })

  it('keeps the editing draft selected for legacy FineCut links', async () => {
    renderShell('/finecut/test-plan')

    const menuItem = (await screen.findByText('剪辑草稿')).closest('li')
    expect(menuItem).toHaveClass('ant-menu-item-selected')
  })

  it('opens the unified editing draft entry', async () => {
    renderShell()

    ;(await screen.findByText('剪辑草稿')).click()

    expect(await screen.findByText('剪辑草稿入口')).toBeInTheDocument()
  })

  it('keeps the sidebar fixed while only the right content pane scrolls', () => {
    renderShell()

    expect(screen.getByTestId('app-sidebar')).toHaveStyle({
      position: 'fixed',
      height: '100vh',
    })
    expect(screen.getByTestId('app-content-scroll')).toHaveStyle({
      overflow: 'auto',
      minHeight: 0,
    })
  })

  it('restores a valid current project using only its id', async () => {
    useAppStore.getState().setCurrentProjectId('project-a')
    renderShell()

    await waitFor(() => expect(screen.getByText('测试项目')).toBeInTheDocument())
    expect(useAppStore.getState().currentProjectId).toBe('project-a')
    expect(Object.keys(useAppStore.getState()).sort()).toEqual([
      'currentProjectId',
      'setCurrentProjectId',
    ])
  })

  it('shows Chinese service health state', async () => {
    renderShell()
    expect(await screen.findByText('服务正常')).toBeInTheDocument()
  })

  it('links to the public source repository', () => {
    renderShell()

    expect(screen.getByRole('link', { name: '源代码' })).toHaveAttribute(
      'href',
      'https://github.com/xinsen854/ClipAtlas',
    )
  })
})
