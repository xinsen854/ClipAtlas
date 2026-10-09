import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as libraryApi from '../../api/library'
import type { LibraryItem } from '../../api/library'
import { useLibraryActions } from './useLibraryActions'

vi.mock('../../api/library', async () => {
  const actual = await vi.importActual<typeof import('../../api/library')>('../../api/library')
  return {
    ...actual,
    addLibraryRoot: vi.fn(),
    parseLibraryItem: vi.fn(),
    reparseLibraryItem: vi.fn(),
    scanLibrary: vi.fn(),
  }
})

function setupHook() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  const hook = renderHook(() => useLibraryActions(), { wrapper })
  return { ...hook, invalidateSpy }
}

const parsedItem: LibraryItem = {
  id: 'item-queued',
  root_id: 'root-1',
  source_path: 'E:/视频素材/等待.mp4',
  size_bytes: 100,
  mtime_ns: 1,
  fingerprint: 'queued',
  processed_fingerprint: 'queued',
  status: 'COMPLETED',
  video_id: 'video-queued',
  attempts: 1,
  last_error: null,
  created_at: '2026-09-03T00:00:00Z',
  updated_at: '2026-09-03T00:01:00Z',
}

const reparsedItem: LibraryItem = {
  ...parsedItem,
  id: 'item-done',
  source_path: 'E:/视频素材/完成.mp4',
  fingerprint: 'done',
  processed_fingerprint: 'done',
  video_id: 'video-done',
  attempts: 2,
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(libraryApi.addLibraryRoot).mockResolvedValue({
    id: 'root-new',
    path: 'E:/视频素材/原样 路径',
    recursive: false,
    enabled: true,
    created_at: '2026-09-03T00:00:00Z',
  })
  vi.mocked(libraryApi.scanLibrary).mockResolvedValue({
    discovered: 0,
    changed: 0,
    missing: 0,
    unchanged: 0,
  })
  vi.mocked(libraryApi.parseLibraryItem).mockResolvedValue(parsedItem)
  vi.mocked(libraryApi.reparseLibraryItem).mockResolvedValue(reparsedItem)
})

describe('useLibraryActions', () => {
  it('passes add-directory payload unchanged and refreshes roots', async () => {
    const { result, invalidateSpy } = setupHook()
    const input = { path: 'E:/视频素材/原样 路径', recursive: false }

    await act(async () => {
      await result.current.addRootMutation.mutateAsync(input)
    })

    expect(libraryApi.addLibraryRoot).toHaveBeenCalledWith(input)
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['library', 'roots'] }),
    )
  })

  it('refreshes item and summary queries after explicit parse', async () => {
    const { result, invalidateSpy } = setupHook()

    await act(async () => {
      await result.current.parseMutation.mutateAsync('item-queued')
    })

    expect(libraryApi.parseLibraryItem).toHaveBeenCalledWith('item-queued')
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['library', 'items'] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['library', 'summary'] })
  })

  it('refreshes item and summary queries after reparse', async () => {
    const { result, invalidateSpy } = setupHook()

    await act(async () => {
      await result.current.reparseMutation.mutateAsync('item-done')
    })

    expect(libraryApi.reparseLibraryItem).toHaveBeenCalledWith('item-done')
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['library', 'items'] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['library', 'summary'] })
  })
})
