import { focusManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/library'
import { LibraryItemPage } from './LibraryItemPage'
import { IndexResultsPage } from './IndexResultsPage'

vi.mock('../../api/library', async () => ({
  ...await vi.importActual<typeof import('../../api/library')>('../../api/library'),
  getLibraryItem: vi.fn(), getVideo: vi.fn(), getVideoIndexProgress: vi.fn(),
  getVideoIndexResults: vi.fn(),
}))

const base = {
  start_ms: 0, end_ms: 5000, provider: 'qwen-vl-video', model: 'qwen3-vl-embedding',
  status: 'completed', last_error: null,
}

function renderPage(path = '/library/items/item-1/index-results') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/library/items/:itemId" element={<LibraryItemPage />} />
          <Route path="/library/items/:itemId/index-results" element={<IndexResultsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getLibraryItem).mockResolvedValue({
    id: 'item-1', video_id: 'video-1', root_id: 'root-1', source_path: 'D:/素材/越野篇.mp4',
    status: 'COMPLETED', size_bytes: 1000, mtime_ns: 1, fingerprint: 'v1',
    processed_fingerprint: 'v1', attempts: 1, last_error: null,
    created_at: '2026-09-05T00:00:00Z', updated_at: '2026-09-05T00:00:00Z',
  })
  vi.mocked(api.getVideo).mockResolvedValue({
    video: {
      id: 'video-1', filename: '越野篇.mp4', duration_ms: 49344, source_uri: 'file:///video.mp4',
      width: 1920, height: 1080, fps: 30, created_at: '2026-09-05T00:00:00Z',
    },
    segment_count: 35,
    annotation_stats: { segments_total: 35, annotated: 0, ai_effective: 0, human_effective: 0, locked: 0 },
  })
  vi.mocked(api.getVideoIndexProgress).mockResolvedValue(Object.fromEntries(
    [['visual', 13], ['asr', 1], ['ocr', 10]].map(([source, count]) => [source, {
      enabled: true, applicable: true, completed: count, total: count, processing: 0, failed: 0,
    }]),
  ) as api.VideoIndexProgress)
  vi.mocked(api.getVideoIndexResults).mockImplementation(async (_video, source, limit = 10, offset = 0) => ({
    source, limit, offset, has_more: source === 'visual' && offset === 0,
    items: source === 'visual' ? [{
      ...base, start_ms: offset * 4000, end_ms: offset * 4000 + 5000,
      dimensions: 2560, chunk_duration_ms: 5000, overlap_ms: 1000, thumbnail_url: '/frame.png',
    }] : source === 'summary' ? [{
      start_ms: 0, end_ms: 28000, summary: '车辆驶入山林道路，随后通过涉水路段。',
      subjects: ['越野车'], actions: ['行驶', '涉水'], scenes: ['山林道路'],
      presentation_type: '全景', pollution_level: 'clean',
    }] : source === 'asr' ? [{
      ...base, provider: 'bailian-asr', model: 'qwen-audio-3.0-asr-flash', end_ms: 49344,
      revision: 1, sentences: [{ start_ms: 7840, end_ms: 9960, text: '领航北路与飞虎。' }],
    }] : [{
      ...base, provider: 'bailian-ocr', model: 'qwen3.5-ocr', revision: 1, interval_ms: 5000,
      readable_text: '专业级氮气减震', text: '<p>专业级氮气减震</p><script>alert(1)</script>',
    }],
  }))
})

describe('index results', () => {
  it('shows all three active stages rather than only the first one', async () => {
    const item = await api.getLibraryItem('item-1')
    vi.mocked(api.getLibraryItem).mockResolvedValue({
      ...item, status: 'FRAME_EXTRACTION', prepared_video_id: 'video-1',
      processing_stages: ['visual', 'asr', 'ocr'], processing_stage: 'visual',
      index_progress: await api.getVideoIndexProgress('video-1'),
    })
    renderPage('/library/items/item-1')
    expect(await screen.findByText('Visual 视频索引')).toBeInTheDocument()
    expect(screen.getByText('ASR 语音识别')).toBeInTheDocument()
    expect(screen.getByText('OCR 文字识别')).toBeInTheDocument()
  })
  it('shows progress and partial results while the completed video id is still null', async () => {
    const item = await api.getLibraryItem('item-1')
    vi.mocked(api.getLibraryItem).mockResolvedValue({
      ...item, status: 'FRAME_EXTRACTION', video_id: null, prepared_video_id: 'video-1',
      index_progress: await api.getVideoIndexProgress('video-1'), processing_stage: 'asr',
      progress_updated_at: '2026-09-06T00:47:26Z',
    })
    vi.mocked(api.getVideoIndexProgress).mockClear()
    renderPage('/library/items/item-1')
    await screen.findByText('ASR 语音识别')
    expect(screen.getByText('13 / 13')).toBeInTheDocument()
    expect(api.getVideoIndexProgress).not.toHaveBeenCalled()
    const user = userEvent.setup()
    await user.click(screen.getByRole('link', { name: '查看解析结果' }))
    await screen.findByText('dimensions: 2560')
    expect(api.getVideoIndexResults).toHaveBeenLastCalledWith('video-1', 'visual', 10, 0)
  }, 20000)

  it('refreshes a running detail stage without user navigation', async () => {
    focusManager.setFocused(true)
    const item = await api.getLibraryItem('item-1')
    const progress = await api.getVideoIndexProgress('video-1')
    vi.mocked(api.getLibraryItem).mockResolvedValue({
      ...item, status: 'FRAME_EXTRACTION', prepared_video_id: 'video-1',
      index_progress: progress, processing_stage: 'asr',
    })
    const view = renderPage('/library/items/item-1')
    try {
      await screen.findByText('ASR 语音识别')
      vi.mocked(api.getLibraryItem).mockResolvedValue({
        ...item, status: 'FRAME_EXTRACTION', prepared_video_id: 'video-1',
        index_progress: progress, processing_stage: 'ocr',
      })
      await screen.findByText('OCR 文字识别', {}, { timeout: 8000 })
    } finally {
      view.unmount()
      focusManager.setFocused(undefined)
    }
  }, 20000)

  it('opens from current progress and loads only selected source/pages; retains raw OCR as text', async () => {
    const user = userEvent.setup()
    const { container } = renderPage('/library/items/item-1')
    await screen.findByText('13 / 13')
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
    expect(screen.getByText('10 / 10')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看片段标注' })).toHaveAttribute('href', '/library/items/item-1/segments')
    await user.click(screen.getByRole('link', { name: '查看解析结果' }))
    await screen.findByText('dimensions: 2560')
    expect(api.getVideoIndexResults).toHaveBeenCalledTimes(1)
    expect(api.getVideoIndexResults).toHaveBeenLastCalledWith('video-1', 'visual', 10, 0)
    expect(screen.getByRole('img', { name: /对应场景缓存帧/ })).toHaveAttribute('src', '/frame.png')
    expect(screen.queryByText(/Synthetic semantic/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(api.getVideoIndexResults).toHaveBeenLastCalledWith('video-1', 'visual', 10, 10))
    await user.click(screen.getByRole('tab', { name: '综合描述' }))
    await screen.findByText('车辆驶入山林道路，随后通过涉水路段。')
    expect(screen.getByText('越野车')).toBeInTheDocument()
    expect(screen.getByText('涉水')).toBeInTheDocument()
    expect(api.getVideoIndexResults).toHaveBeenLastCalledWith('video-1', 'summary', 10, 0)

    await user.click(screen.getByRole('tab', { name: 'ASR' }))
    await screen.findByText('领航北路与飞虎。')
    expect(screen.getByText('00:07.840 – 00:09.960')).toBeInTheDocument()
    expect(api.getVideoIndexResults).toHaveBeenLastCalledWith('video-1', 'asr', 10, 0)
    await user.click(screen.getByRole('tab', { name: 'OCR' }))
    await screen.findByText('专业级氮气减震')
    const raw = screen.getByText('<p>专业级氮气减震</p><script>alert(1)</script>')
    expect(raw).not.toBeVisible()
    await user.click(screen.getByText('查看原始 OCR 文本'))
    expect(raw).toBeVisible()
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
    expect(screen.getByRole('link', { name: '片段标注与人工修正' })).toBeInTheDocument()
  }, 20000)


  it('shows empty and failed result requests without hiding navigation', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getVideoIndexResults).mockResolvedValueOnce({ source: 'visual', items: [], limit: 10, offset: 0, has_more: false })
    renderPage()
    await screen.findByText('暂无已保存的解析结果')
    vi.mocked(api.getVideoIndexResults).mockRejectedValueOnce(new Error('read failed'))
    await user.click(screen.getByRole('tab', { name: 'ASR' }))
    await screen.findByText('解析结果读取失败')
    expect(screen.getByRole('link', { name: '返回素材详情' })).toBeInTheDocument()
  })
})
