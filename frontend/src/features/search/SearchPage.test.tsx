import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as searchApi from '../../api/search'
import type {
  HybridSearchHit,
  SemanticSearchHit,
  VideoChunkSearchHit,
} from '../../api/search'
import { SearchPage } from './SearchPage'

vi.mock('../../api/search', async () => {
  const actual = await vi.importActual<typeof import('../../api/search')>('../../api/search')
  return {
    ...actual,
    searchHybrid: vi.fn(),
    searchSegments: vi.fn(),
    searchVideoChunks: vi.fn(),
  }
})

const hybridHit: HybridSearchHit = {
  video_id: 'video-hybrid',
  filename: '越野测试.mp4',
  source_uri: 'D:/素材库/越野测试.mp4',
  source_start_ms: 10_000,
  source_end_ms: 18_000,
  score: 2.05,
  visual_score: 0.81,
  asr_score: 0.64,
  ocr_score: 0.6,
  sources: ['visual', 'asr', 'ocr'],
  asr_texts: ['我们现在进入越野测试路段'],
  ocr_texts: ['越野测试'],
}

const semanticHit: SemanticSearchHit = {
  segment_id: 'segment-1',
  video_id: 'video-1',
  source_uri: 'D:/素材库/雨夜街景.mp4',
  source_start_ms: 1200,
  source_end_ms: 5400,
  score: 0.9134,
  effective_description: '雨夜街口，一名女子撑伞等待公交。',
  annotation: {
    id: 'annotation-1',
    segment_id: 'segment-1',
    origin: 'human',
    provider: null,
    model: null,
    description: '雨夜街口，一名女子撑伞等待公交。',
    characters: ['女子'],
    actions: ['撑伞', '等待'],
    scene: ['雨夜', '街口'],
    emotions: ['焦虑'],
    objects: ['雨伞'],
    ocr: ['公交站'],
    shot_type: '中景',
    camera_motion: '固定',
    confidence: 0.91,
    verified: true,
    locked: true,
    revision: 4,
    raw_payload: {},
    created_at: '2026-09-03T00:00:00Z',
  },
  embedding_provider: 'dashscope',
  embedding_model: 'text-embedding-v4',
  embedding_dimensions: 1024,
}

const videoHit: VideoChunkSearchHit = {
  video_id: 'video-2',
  filename: '夜间山路.mp4',
  source_uri: 'D:/素材库/夜间山路.mp4',
  source_start_ms: 76_000,
  source_end_ms: 81_000,
  score: 0.775897,
  embedding_provider: 'qwen-vl-video',
  embedding_model: 'qwen3-vl-embedding',
  embedding_dimensions: 2560,
  chunk_duration_ms: 5_000,
  overlap_ms: 1_000,
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(searchApi.searchHybrid).mockResolvedValue([hybridHit])
  vi.mocked(searchApi.searchSegments).mockResolvedValue([semanticHit])
  vi.mocked(searchApi.searchVideoChunks).mockResolvedValue([videoHit])
})

describe('SearchPage', () => {
  it('defaults to hybrid recall and renders source provenance', async () => {
    renderPage()

    expect(screen.getByRole('radio', { name: '混合召回' })).toBeChecked()
    fireEvent.change(screen.getByLabelText('搜索素材'), {
      target: { value: '越野测试' },
    })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))

    await waitFor(() =>
      expect(searchApi.searchHybrid).toHaveBeenCalledWith({
        q: '越野测试',
        limit: 20,
      }),
    )
    expect(await screen.findByText('越野测试.mp4')).toBeInTheDocument()
    expect(screen.getByText('视觉 0.8100')).toBeInTheDocument()
    expect(screen.getByText('ASR 0.6400')).toBeInTheDocument()
    expect(screen.getByText('OCR 0.6000')).toBeInTheDocument()
    expect(screen.getByText('我们现在进入越野测试路段')).toBeInTheDocument()
    expect(searchApi.searchVideoChunks).not.toHaveBeenCalled()
    expect(searchApi.searchSegments).not.toHaveBeenCalled()
  })

  it('renders video-vector hits with backend filename score and exact time range', async () => {
    renderPage()

    fireEvent.click(screen.getByRole('radio', { name: '视频向量 · 5 秒' }))
    fireEvent.change(screen.getByLabelText('搜索素材'), { target: { value: '夜间山路' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))

    expect(await screen.findByText('夜间山路.mp4')).toBeInTheDocument()
    expect(screen.getByText('匹配分数 0.7759')).toBeInTheDocument()
    expect(screen.getByText('01:16.000 — 01:21.000')).toBeInTheDocument()
    expect(screen.getByText('5秒向量')).toBeInTheDocument()
    expect(screen.queryByText('qwen3-vl-embedding')).not.toBeInTheDocument()
    expect(screen.queryByText('2560')).not.toBeInTheDocument()
  })

  it('can explicitly switch search to the optional 30s vector profile', async () => {
    renderPage()

    fireEvent.click(screen.getByRole('radio', { name: '视频向量 · 30 秒' }))
    fireEvent.change(screen.getByLabelText('搜索素材'), { target: { value: '越野篇' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))

    await waitFor(() =>
      expect(searchApi.searchVideoChunks).toHaveBeenCalledWith({
        q: '越野篇',
        limit: 20,
        granularity: '30s',
      }),
    )
    expect(searchApi.searchSegments).not.toHaveBeenCalled()
  })

  it('keeps the existing deep semantic annotation search and expandable annotation', async () => {
    renderPage()

    fireEvent.click(screen.getByRole('radio', { name: '深度语义标注' }))
    fireEvent.change(screen.getByLabelText('搜索素材'), { target: { value: '雨夜等公交' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))

    await waitFor(() =>
      expect(searchApi.searchSegments).toHaveBeenCalledWith({
        q: '雨夜等公交',
        limit: 20,
      }),
    )
    expect(searchApi.searchVideoChunks).not.toHaveBeenCalled()
    expect(await screen.findByText('雨夜街景.mp4')).toBeInTheDocument()
    expect(screen.getByText('雨夜街口，一名女子撑伞等待公交。')).toBeInTheDocument()
    expect(screen.getByText('人工修正')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '查看标注' }))
    expect(screen.getByText('公交站')).toBeInTheDocument()
    expect(screen.getByText('中景')).toBeInTheDocument()
    expect(screen.getByText('固定')).toBeInTheDocument()
    expect(screen.getByText('修订 4')).toBeInTheDocument()
    expect(screen.getByText('已锁定')).toBeInTheDocument()
  })
})
