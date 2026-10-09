import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as libraryApi from '../../api/library'
import type { AnnotationCorrectionResponse, UpdateAnnotationInput } from '../../api/library'
import { useAnnotationCorrection } from './useAnnotationCorrection'

vi.mock('../../api/library', async () => {
  const actual = await vi.importActual<typeof import('../../api/library')>('../../api/library')
  return {
    ...actual,
    updateSegmentAnnotation: vi.fn(),
  }
})

const response: AnnotationCorrectionResponse = {
  annotation: {
    id: 'annotation-human-4',
    segment_id: 'segment-1',
    origin: 'human',
    provider: null,
    model: null,
    description: '人工修正后的描述',
    characters: ['女子'],
    actions: ['等待'],
    scene: ['雨夜'],
    emotions: ['焦虑'],
    objects: ['雨伞'],
    ocr: [],
    shot_type: '中景',
    camera_motion: '固定',
    confidence: 0.95,
    verified: true,
    locked: true,
    revision: 4,
    raw_payload: {},
    created_at: '2026-09-03T00:00:00Z',
  },
  embedding_updated: true,
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(libraryApi.updateSegmentAnnotation).mockResolvedValue(response)
})

describe('useAnnotationCorrection', () => {
  it('sends the exact correction payload and refreshes segment and video detail caches', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const { result } = renderHook(() => useAnnotationCorrection('video-1'), {
      wrapper: createWrapper(queryClient),
    })
    const input: UpdateAnnotationInput = {
      description: '人工修正后的描述',
      characters: ['女子'],
      locked: true,
    }

    act(() => {
      result.current.mutate({ segmentId: 'segment-1', input })
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(libraryApi.updateSegmentAnnotation).toHaveBeenCalledWith('segment-1', input)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['video', 'segments', 'video-1'] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['video', 'video-1'] })
    expect(result.current.data?.embedding_updated).toBe(true)
  })
})
