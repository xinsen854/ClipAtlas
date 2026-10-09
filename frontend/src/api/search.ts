import { apiRequest } from './client'
import type { SemanticAnnotation } from './library'

export type SemanticSearchHit = {
  segment_id: string
  video_id: string
  source_uri: string
  source_start_ms: number
  source_end_ms: number
  score: number
  effective_description: string
  annotation: SemanticAnnotation
  embedding_provider: string
  embedding_model: string
  embedding_dimensions: number
}

export type VideoChunkSearchHit = {
  video_id: string
  filename: string
  source_uri: string
  source_start_ms: number
  source_end_ms: number
  score: number
  embedding_provider: string
  embedding_model: string
  embedding_dimensions: number
  chunk_duration_ms: number
  overlap_ms: number
}

export type RecallSource = 'visual' | 'asr' | 'ocr'

export type HybridSearchHit = {
  video_id: string
  filename: string
  source_uri: string
  source_start_ms: number
  source_end_ms: number
  score: number
  visual_score: number | null
  asr_score: number | null
  ocr_score: number | null
  sources: RecallSource[]
  asr_texts: string[]
  ocr_texts: string[]
}

export type SearchSegmentsParams = {
  q: string
  limit?: number
  videoIds?: string[]
  projectId?: string | null
}

export type VideoSearchGranularity = '5s' | '30s'

export type SearchVideoChunksParams = {
  q: string
  limit?: number
  videoIds?: string[]
  projectId?: string | null
  granularity?: VideoSearchGranularity
}

export function searchHybrid({
  q,
  limit = 10,
  videoIds,
  projectId,
}: SearchSegmentsParams): Promise<HybridSearchHit[]> {
  const query = new URLSearchParams({ q, limit: String(limit) })
  for (const videoId of videoIds ?? []) {
    query.append('video_ids', videoId)
  }
  if (projectId) query.set('project_id', projectId)
  return apiRequest<HybridSearchHit[]>(`/api/v1/search/hybrid?${query.toString()}`)
}

export function searchSegments({ q, limit = 10, videoIds, projectId }: SearchSegmentsParams): Promise<SemanticSearchHit[]> {
  const query = new URLSearchParams({ q, limit: String(limit) })
  for (const videoId of videoIds ?? []) {
    query.append('video_ids', videoId)
  }
  if (projectId) query.set('project_id', projectId)
  return apiRequest<SemanticSearchHit[]>(`/api/v1/search/segments?${query.toString()}`)
}

export function searchVideoChunks({
  q,
  limit = 10,
  videoIds,
  granularity = '5s',
  projectId,
}: SearchVideoChunksParams): Promise<VideoChunkSearchHit[]> {
  const query = new URLSearchParams({
    q,
    limit: String(limit),
    granularity,
  })
  for (const videoId of videoIds ?? []) {
    query.append('video_ids', videoId)
  }
  if (projectId) query.set('project_id', projectId)
  return apiRequest<VideoChunkSearchHit[]>(`/api/v1/search/video-chunks?${query.toString()}`)
}
