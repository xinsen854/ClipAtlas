import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as libraryApi from '../../api/library'
import * as segmentRolesApi from '../../api/segmentRoles'
import type { LibraryItem, SegmentPage } from '../../api/library'
import { SegmentAnnotationsPage, segmentPageOffset } from './SegmentAnnotationsPage'

vi.mock('../../api/library', async () => {
  const actual = await vi.importActual<typeof import('../../api/library')>('../../api/library')
  return {
    ...actual,
    getLibraryItem: vi.fn(),
    getVideoSegments: vi.fn(),
  }
})

vi.mock('../../api/segmentRoles', async () => {
  const actual = await vi.importActual<typeof import('../../api/segmentRoles')>('../../api/segmentRoles')
  return {
    ...actual,
    setSegmentFallbackRole: vi.fn(),
  }
})

const item: LibraryItem = {
  id: 'item-1',
  root_id: 'root-1',
  source_path: 'D:/素材库/街景.mp4',
  size_bytes: 100,
  mtime_ns: 1,
  fingerprint: 'fingerprint',
  processed_fingerprint: 'fingerprint',
  status: 'COMPLETED',
  video_id: 'video-1',
  attempts: 1,
  last_error: null,
  created_at: '2026-09-03T00:00:00Z',
  updated_at: '2026-09-03T00:00:00Z',
}

const segmentPage: SegmentPage = {
  items: [
    {
      segment: {
        id: 'segment-1',
        video_id: 'video-1',
        start_ms: 1200,
        end_ms: 5400,
        source: 'scene_detection',
        created_at: '2026-09-03T00:00:00Z',
      },
      annotation: {
        id: 'annotation-1',
        segment_id: 'segment-1',
        origin: 'human',
        provider: null,
        model: null,
        description: '雨夜街口，一名女子撑伞等待。',
        characters: ['女子'],
        actions: ['撑伞', '等待'],
        scene: ['雨夜', '街口'],
        emotions: ['克制', '焦虑'],
        objects: ['雨伞'],
        ocr: ['公交站'],
        shot_type: '中景',
        camera_motion: '固定',
        confidence: 0.91,
        verified: true,
        locked: true,
        revision: 3,
        raw_payload: {},
        created_at: '2026-09-03T00:00:00Z',
      },
    },
  ],
  total: 51,
  limit: 50,
  offset: 0,
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/library/items/item-1/segments']}>
        <Routes>
          <Route path="/library/items/:itemId/segments" element={<SegmentAnnotationsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(libraryApi.getLibraryItem).mockResolvedValue(item)
  vi.mocked(libraryApi.getVideoSegments).mockResolvedValue(segmentPage)
  vi.mocked(segmentRolesApi.setSegmentFallbackRole).mockResolvedValue({
    segment_id: 'segment-1', role: 'generic',
  })
})

describe('SegmentAnnotationsPage', () => {
  it('loads the material deep link and renders the current effective annotation', async () => {
    renderPage()

    await screen.findByText('雨夜街口，一名女子撑伞等待。')
    expect(libraryApi.getLibraryItem).toHaveBeenCalledWith('item-1')
    expect(libraryApi.getVideoSegments).toHaveBeenCalledWith('video-1', 50, 0)
    expect(screen.getByText('人工修正')).toBeInTheDocument()
    expect(screen.getByText('修订 3')).toBeInTheDocument()
    expect(screen.getByText('已锁定')).toBeInTheDocument()
    expect(screen.getByText('女子')).toBeInTheDocument()
    expect(screen.getByText('焦虑')).toBeInTheDocument()
    expect(screen.getByText(/通用空镜用于 exact/)).toBeInTheDocument()
  })

  it('allows one segment to be marked as generic b-roll', async () => {
    const user = userEvent.setup()
    renderPage()

    const select = await screen.findByRole('combobox', { name: '片段 1 用途' })
    await user.click(select)
    await user.click(await screen.findByText('通用空镜'))

    await waitFor(() => {
      expect(segmentRolesApi.setSegmentFallbackRole).toHaveBeenCalledWith('segment-1', 'generic')
    })
    await waitFor(() => expect(libraryApi.getVideoSegments).toHaveBeenCalledTimes(2))
  })

  it('uses stable zero-based offsets for paginated segment requests', async () => {
    expect(segmentPageOffset(1, 50)).toBe(0)
    expect(segmentPageOffset(2, 50)).toBe(50)
    expect(segmentPageOffset(3, 25)).toBe(50)

    renderPage()
    await waitFor(() => expect(libraryApi.getVideoSegments).toHaveBeenCalledTimes(1))
  })
})
