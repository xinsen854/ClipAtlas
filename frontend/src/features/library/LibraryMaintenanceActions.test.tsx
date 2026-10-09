import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import * as api from '../../api/library'
import { LibraryMaintenanceActions } from './LibraryMaintenanceActions'

vi.mock('../../api/library', () => ({
  getLibraryItems: vi.fn(), pauseLibraryProcessing: vi.fn(),
  reparseLibraryItem: vi.fn(), resetLibraryAnalysis: vi.fn(),
}))

function page(busy = false) {
  render(<QueryClientProvider client={new QueryClient()}>
    <LibraryMaintenanceActions available busy={busy} />
  </QueryClientProvider>)
}

beforeEach(() => { vi.clearAllMocks() })

it('requires destructive confirmation and explains shared-library scope', async () => {
  vi.mocked(api.resetLibraryAnalysis).mockResolvedValue({ items_reset: 11, cache_directories_removed: 14, backup_path: '/backup', warning: null })
  page()
  fireEvent.click(screen.getByRole('button', { name: '清空解析结果与缓存' }))
  await screen.findByText('这是所有项目共享的素材库，不只是当前项目。')
  expect(api.resetLibraryAnalysis).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
  expect(api.resetLibraryAnalysis).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '清空解析结果与缓存' }))
  fireEvent.click(screen.getByRole('button', { name: '确认清空' }))
  await waitFor(() => expect(api.resetLibraryAnalysis).toHaveBeenCalledOnce())
  await screen.findByText(/已清空 11 个素材/)
})

it('reads all pages and reparses completed and queued items, skipping missing files', async () => {
  const missing = { id: 'missing', status: 'MISSING', source_path: '/missing.mp4' } as api.LibraryItem
  const completed = { id: 'done', status: 'COMPLETED', source_path: '/done.mp4' } as api.LibraryItem
  const queued = { id: 'queued', status: 'QUEUED', source_path: '/new.mp4' } as api.LibraryItem
  vi.mocked(api.getLibraryItems).mockResolvedValueOnce(Array.from({ length: 500 }, () => missing))
    .mockResolvedValueOnce([completed, queued])
  vi.mocked(api.pauseLibraryProcessing).mockResolvedValue({ available: true, paused: true })
  vi.mocked(api.reparseLibraryItem).mockResolvedValue(completed)
  page()
  fireEvent.click(screen.getByRole('button', { name: '全部重新解析' }))
  expect(api.reparseLibraryItem).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '开始全部重新解析' }))
  await screen.findByText(/全部重新解析结束：已处理 2 个/)
  expect(api.getLibraryItems).toHaveBeenNthCalledWith(2, { limit: 500, offset: 500 })
  expect(vi.mocked(api.reparseLibraryItem).mock.calls.map(([id]) => id)).toEqual(['done', 'queued'])
  expect(api.resetLibraryAnalysis).not.toHaveBeenCalled()
})

it('disables destructive and batch operations while an item is processing', () => {
  page(true)
  expect(screen.getByRole('button', { name: '全部重新解析' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '清空解析结果与缓存' })).toBeDisabled()
})
