import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as libraryApi from '../../api/library'
import type { LibraryItem, LibrarySummary } from '../../api/library'
import { LibraryPage, shouldPollLibrary } from './LibraryPage'

const processingMocks = vi.hoisted(() => ({
  get: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
}))

vi.mock('../../api/library', async () => {
  const actual = await vi.importActual<typeof import('../../api/library')>('../../api/library')
  return {
    ...actual,
    addLibraryRoot: vi.fn(),
    getLibraryItems: vi.fn(),
    getLibrarySummary: vi.fn(),
    listLibraryRoots: vi.fn(),
    parseLibraryItem: vi.fn(),
    reparseLibraryItem: vi.fn(),
    retryLibraryItem: vi.fn(),
    scanLibrary: vi.fn(),
    getLibraryProcessingState: processingMocks.get,
    pauseLibraryProcessing: processingMocks.pause,
    resumeLibraryProcessing: processingMocks.resume,
  }
})

vi.mock('./LibraryRootDialog', () => ({
  LibraryRootDialog: () => null,
}))

function summary(overrides: Partial<LibrarySummary> = {}): LibrarySummary {
  return {
    QUEUED: 1,
    PROBING: 0,
    SCENE_DETECTION: 0,
    FRAME_EXTRACTION: 0,
    COMPLETED: 1,
    FAILED: 1,
    MISSING: 0,
    ...overrides,
  }
}

const failedItem: LibraryItem = {
  id: 'item-failed',
  root_id: 'root-1',
  source_path: 'D:/素材库/失败.mp4',
  size_bytes: 100,
  mtime_ns: 1,
  fingerprint: 'failed',
  processed_fingerprint: null,
  status: 'FAILED',
  video_id: null,
  attempts: 1,
  last_error: 'boom',
  created_at: '2026-09-03T00:00:00Z',
  updated_at: '2026-09-03T00:00:00Z',
}

const completedItem: LibraryItem = {
  ...failedItem,
  id: 'item-done',
  source_path: 'D:/素材库/完成.mp4',
  fingerprint: 'done',
  status: 'COMPLETED',
  video_id: 'video-done',
  last_error: null,
}

const queuedItem: LibraryItem = {
  ...failedItem,
  id: 'item-queued',
  source_path: 'D:/素材库/等待.mp4',
  fingerprint: 'queued',
  status: 'QUEUED',
  attempts: 0,
  last_error: null,
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <LibraryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { queryClient, invalidateSpy }
}

function rowFor(filename: string): HTMLElement {
  const row = screen.getByText(filename).closest('tr')
  if (!row) throw new Error(`row not found for ${filename}`)
  return row
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(libraryApi.listLibraryRoots).mockResolvedValue([])
  vi.mocked(libraryApi.getLibrarySummary).mockResolvedValue(summary())
  vi.mocked(libraryApi.getLibraryItems).mockResolvedValue([queuedItem, failedItem, completedItem])
  vi.mocked(libraryApi.scanLibrary).mockResolvedValue({
    discovered: 0,
    changed: 0,
    missing: 0,
    unchanged: 0,
  })
  vi.mocked(libraryApi.parseLibraryItem).mockResolvedValue({
    ...queuedItem,
    status: 'COMPLETED',
    video_id: 'video-queued',
    attempts: 1,
  })
  vi.mocked(libraryApi.reparseLibraryItem).mockImplementation(async (itemId) => ({
    ...(itemId === failedItem.id ? failedItem : completedItem),
    status: 'COMPLETED',
    video_id: itemId === failedItem.id ? 'video-recovered' : completedItem.video_id,
    attempts: 2,
    last_error: null,
  }))
  processingMocks.get.mockResolvedValue({ available: true, paused: false })
  processingMocks.pause.mockResolvedValue({ available: true, paused: true })
  processingMocks.resume.mockResolvedValue({ available: true, paused: false })
})

describe('LibraryPage', () => {
  it('shows queued items separately from running work after a paused reset', async () => {
    processingMocks.get.mockResolvedValue({ available: true, paused: true })
    vi.mocked(libraryApi.getLibrarySummary).mockResolvedValue(summary({
      QUEUED: 11, COMPLETED: 0, FAILED: 0,
    }))
    vi.mocked(libraryApi.getLibraryItems).mockResolvedValue([])
    renderPage()

    const waiting = (await screen.findByText('等待解析')).closest('.ant-statistic')
    const processing = screen.getByText('解析中').closest('.ant-statistic')
    expect(waiting).toHaveTextContent('11')
    expect(processing).toHaveTextContent('0')
    expect(screen.getByText('后台自动解析已暂停，等待解析的素材不会自动开始。')).toBeInTheDocument()
    expect(libraryApi.parseLibraryItem).not.toHaveBeenCalled()
    expect(libraryApi.reparseLibraryItem).not.toHaveBeenCalled()
    expect(processingMocks.resume).not.toHaveBeenCalled()
  })

  it('passes the selected parsing status to the backend list query', async () => {
    renderPage()

    await screen.findByText('失败.mp4')
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '解析状态' }))
    const listbox = await screen.findByRole('listbox')
    fireEvent.click(within(listbox).getByRole('option', { name: '解析失败' }))

    await waitFor(() =>
      expect(libraryApi.getLibraryItems).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: 'FAILED' }),
      ),
    )
  })

  it('uses checkpoint retry for failed items and force reparse only for completed items', async () => {
    const user = userEvent.setup()
    const { invalidateSpy } = renderPage()

    await screen.findByText('等待.mp4')
    const queuedRow = within(rowFor('等待.mp4'))
    const failedRow = within(rowFor('失败.mp4'))
    const completedRow = within(rowFor('完成.mp4'))

    expect(queuedRow.getByRole('button', { name: '单条解析' })).toBeEnabled()
    expect(failedRow.getByRole('button', { name: '重试' })).toBeEnabled()
    expect(completedRow.getByRole('button', { name: '重新解析' })).toBeEnabled()
    vi.mocked(libraryApi.retryLibraryItem).mockResolvedValue({ status: 'QUEUED' })
    await user.click(failedRow.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(libraryApi.retryLibraryItem).toHaveBeenCalledWith('item-failed'))
    expect(libraryApi.reparseLibraryItem).not.toHaveBeenCalled()

    await user.click(queuedRow.getByRole('button', { name: '单条解析' }))
    await waitFor(() => expect(libraryApi.parseLibraryItem).toHaveBeenCalledWith('item-queued'))
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['library', 'items'] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['library', 'summary'] })

    await user.click(completedRow.getByRole('button', { name: '重新解析' }))
    await waitFor(() => expect(libraryApi.reparseLibraryItem).toHaveBeenCalledWith('item-done'))
  })

  it('keeps explicit row parsing available while background parsing is paused', async () => {
    processingMocks.get.mockResolvedValue({ available: true, paused: true })
    renderPage()

    await screen.findByText('等待.mp4')
    expect(within(rowFor('等待.mp4')).getByRole('button', { name: '单条解析' })).toBeEnabled()
    expect(within(rowFor('完成.mp4')).getByRole('button', { name: '重新解析' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '继续未完成' })).toBeInTheDocument()
  })

  it('pauses background parsing through the explicit runtime control', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('失败.mp4')
    await user.click(screen.getByRole('button', { name: '暂停解析' }))

    await waitFor(() => expect(processingMocks.pause).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('button', { name: '继续未完成' })).toBeInTheDocument()
  })

  it('keeps scanning available but disables explicit parsing without a provider', async () => {
    processingMocks.get.mockResolvedValue({ available: false, paused: true })
    renderPage()

    expect(await screen.findByText(/尚未配置视频理解 API/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '扫描素材' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: '继续未完成' })).not.toBeInTheDocument()
    expect(within(rowFor('等待.mp4')).getByRole('button', { name: '单条解析' })).toBeDisabled()
    expect(within(rowFor('完成.mp4')).getByRole('button', { name: '重新解析' })).toBeDisabled()
  })
})

describe('library polling policy', () => {
  it('polls only while non-terminal work exists, parsing is active, and the page is visible', () => {
    expect(shouldPollLibrary(summary({ QUEUED: 1 }), true, true)).toBe(true)
    expect(shouldPollLibrary(summary({ PROBING: 1 }), true, true)).toBe(true)
    expect(shouldPollLibrary(summary({ FRAME_EXTRACTION: 1 }), false, true)).toBe(false)
    expect(shouldPollLibrary(summary({ QUEUED: 1 }), true, false)).toBe(false)
    expect(shouldPollLibrary(summary({ QUEUED: 0, FAILED: 3 }), true, true)).toBe(false)
  })
})
