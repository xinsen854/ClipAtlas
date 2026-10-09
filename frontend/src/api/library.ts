import { apiRequest } from './client'
import type { LibraryItemStatus } from '../utils/statusMaps'

export type CacheLocation = { path: string; restart_required: boolean; environment_managed: boolean }
export type CacheMoveResult = {
  path: string; previous_path: string; files_moved: number; restart_required: boolean
  backup_path: string | null; warning: string | null
}
export function getCacheLocation(): Promise<CacheLocation> {
  return apiRequest('/api/v1/library/cache-location')
}
export function moveCacheLocation(path: string): Promise<CacheMoveResult> {
  return apiRequest('/api/v1/library/cache-location', {
    method: 'POST', body: JSON.stringify({ path, confirm: 'MOVE_LIBRARY_CACHE' }),
  })
}

export type LibraryRoot = {
  id: string
  path: string
  recursive: boolean
  enabled: boolean
  project_id?: string | null
  created_at: string
}

export type LibraryItem = {
  id: string
  root_id: string
  source_path: string
  size_bytes: number
  mtime_ns: number
  fingerprint: string
  processed_fingerprint: string | null
  status: LibraryItemStatus
  video_id: string | null
  prepared_video_id?: string | null
  index_progress?: VideoIndexProgress | null
  processing_stage?: 'visual' | 'asr' | 'ocr' | 'finalizing' | null
  processing_stages?: ('visual' | 'asr' | 'ocr')[]
  progress_updated_at?: string | null
  attempts: number
  last_error: string | null
  created_at: string
  updated_at: string
}

export type LibrarySummary = Record<LibraryItemStatus, number>

export type LibraryProcessingState = {
  available: boolean
  paused: boolean
}

export type ScanReport = {
  discovered: number
  changed: number
  missing: number
  unchanged: number
}

export type SegmentSource = 'scene_detection' | 'ai' | 'manual'
export type AnnotationOrigin = 'ai' | 'human'

export type VideoAsset = {
  id: string
  filename: string
  source_uri: string
  duration_ms: number | null
  width: number | null
  height: number | null
  fps: number | null
  created_at: string
  fallback_role?: 'normal' | 'generic' | 'never'
}

export type VideoSegment = {
  id: string
  video_id: string
  start_ms: number
  end_ms: number
  source: SegmentSource
  created_at: string
}

export type SemanticAnnotation = {
  id: string
  segment_id: string
  origin: AnnotationOrigin
  provider: string | null
  model: string | null
  description: string
  characters: string[]
  actions: string[]
  scene: string[]
  emotions: string[]
  objects: string[]
  ocr: string[]
  shot_type: string | null
  camera_motion: string | null
  confidence: number | null
  verified: boolean
  locked: boolean
  revision: number
  raw_payload: Record<string, unknown>
  created_at: string
}

export type VideoAnnotationStats = {
  segments_total: number
  annotated: number
  ai_effective: number
  human_effective: number
  locked: number
}

export type VideoDetailResponse = {
  video: VideoAsset
  segment_count: number
  annotation_stats: VideoAnnotationStats
}

export type IndexSourceProgress = {
  enabled: boolean
  applicable: boolean
  completed: number
  processing: number
  failed: number
  total: number
}

export type VideoIndexProgress = {
  visual: IndexSourceProgress
  asr: IndexSourceProgress
  ocr: IndexSourceProgress
}

export type IndexSource = 'visual' | 'summary' | 'asr' | 'ocr'

type IndexRecord = {
  start_ms: number
  end_ms: number
  provider: string
  model: string
  status: string
  last_error: string | null
}

export type VisualIndexResult = IndexRecord & {
  dimensions: number | null
  chunk_duration_ms: number
  overlap_ms: number
  thumbnail_url: string | null
}

export type ASRIndexResult = IndexRecord & {
  revision: number
  sentences: { start_ms: number; end_ms: number; text: string }[]
}

export type OCRIndexResult = IndexRecord & {
  revision: number
  interval_ms: number
  text: string
  readable_text: string
}

export type SemanticSpanIndexResult = {
  start_ms: number
  end_ms: number
  summary: string
  subjects: string[]
  actions: string[]
  scenes: string[]
  presentation_type: string | null
  pollution_level: 'clean' | 'text_heavy' | 'blocked'
}

export type IndexResultsPage = {
  source: IndexSource
  items: (VisualIndexResult | SemanticSpanIndexResult | ASRIndexResult | OCRIndexResult)[]
  limit: number
  offset: number
  has_more: boolean
}

export type SegmentSummary = {
  segment: VideoSegment
  annotation: SemanticAnnotation | null
}

export type SegmentPage = {
  items: SegmentSummary[]
  total: number
  limit: number
  offset: number
}

export type AddLibraryRootInput = {
  path: string
  recursive?: boolean
  projectId?: string | null
}

export type LibraryItemsParams = {
  rootId?: string
  status?: LibraryItemStatus
  projectId?: string | null
  limit?: number
  offset?: number
}

export type UpdateAnnotationInput = Partial<
  Pick<
    SemanticAnnotation,
    | 'description'
    | 'characters'
    | 'actions'
    | 'scene'
    | 'emotions'
    | 'objects'
    | 'ocr'
    | 'shot_type'
    | 'camera_motion'
    | 'confidence'
    | 'locked'
  >
>

export type AnnotationCorrectionResponse = {
  annotation: SemanticAnnotation
  embedding_updated: boolean
}

export function addLibraryRoot(input: AddLibraryRootInput): Promise<LibraryRoot> {
  const payload: Record<string, unknown> = {
    path: input.path,
    recursive: input.recursive ?? true,
  }
  if (input.projectId) payload.project_id = input.projectId
  return apiRequest<LibraryRoot>('/api/v1/library/roots', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listLibraryRoots(projectId?: string | null): Promise<LibraryRoot[]> {
  const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
  return apiRequest<LibraryRoot[]>(`/api/v1/library/roots${suffix}`)
}

export function getLibraryItems(params: LibraryItemsParams = {}): Promise<LibraryItem[]> {
  const query = new URLSearchParams()
  if (params.rootId) query.set('root_id', params.rootId)
  if (params.status) query.set('status', params.status)
  if (params.projectId) query.set('project_id', params.projectId)
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.offset !== undefined) query.set('offset', String(params.offset))
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest<LibraryItem[]>(`/api/v1/library/items${suffix}`)
}

export function getLibraryItem(itemId: string): Promise<LibraryItem> {
  return apiRequest<LibraryItem>(`/api/v1/library/items/${encodeURIComponent(itemId)}`)
}

export function getLibrarySummary(projectId?: string | null): Promise<LibrarySummary> {
  const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
  return apiRequest<LibrarySummary>(`/api/v1/library/summary${suffix}`)
}

export function getLibraryProcessingState(): Promise<LibraryProcessingState> {
  return apiRequest<LibraryProcessingState>('/api/v1/library/processing')
}

export function pauseLibraryProcessing(): Promise<LibraryProcessingState> {
  return apiRequest<LibraryProcessingState>('/api/v1/library/processing/pause', {
    method: 'POST',
  })
}

export function resumeLibraryProcessing(): Promise<LibraryProcessingState> {
  return apiRequest<LibraryProcessingState>('/api/v1/library/processing/resume', {
    method: 'POST',
  })
}

export function scanLibrary(): Promise<ScanReport> {
  return apiRequest<ScanReport>('/api/v1/library/scan', { method: 'POST' })
}

export interface LibrarySupplementResult {
  failed: number
  interrupted: number
  incomplete: number
  total: number
}

export function supplementLibrary(): Promise<LibrarySupplementResult> {
  return apiRequest<LibrarySupplementResult>('/api/v1/library/supplement', {
    method: 'POST',
  })
}

export function parseLibraryItem(itemId: string): Promise<LibraryItem> {
  return apiRequest<LibraryItem>(
    `/api/v1/library/items/${encodeURIComponent(itemId)}/parse`,
    { method: 'POST' },
  )
}

export function reparseLibraryItem(itemId: string): Promise<LibraryItem> {
  return apiRequest<LibraryItem>(
    `/api/v1/library/items/${encodeURIComponent(itemId)}/reparse`,
    { method: 'POST' },
  )
}

export function retryLibraryItem(itemId: string): Promise<{ status: 'QUEUED' }> {
  return apiRequest<{ status: 'QUEUED' }>(
    `/api/v1/library/items/${encodeURIComponent(itemId)}/retry`,
    { method: 'POST' },
  )
}

export function getVideo(videoId: string): Promise<VideoDetailResponse> {
  return apiRequest<VideoDetailResponse>(`/api/v1/videos/${encodeURIComponent(videoId)}`)
}

export function updateVideoFallbackRole(
  videoId: string, role: 'normal' | 'generic' | 'never',
): Promise<VideoAsset> {
  return apiRequest<VideoAsset>(`/api/v1/videos/${encodeURIComponent(videoId)}/fallback-role`, {
    method: 'PATCH', body: JSON.stringify({ role }),
  })
}

export function getVideoIndexProgress(videoId: string): Promise<VideoIndexProgress> {
  return apiRequest<VideoIndexProgress>(
    `/api/v1/videos/${encodeURIComponent(videoId)}/index-progress`,
  )
}

export function getVideoSegments(videoId: string, limit = 50, offset = 0): Promise<SegmentPage> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  return apiRequest<SegmentPage>(
    `/api/v1/videos/${encodeURIComponent(videoId)}/segments?${query.toString()}`,
  )
}

export function resetLibraryAnalysis(): Promise<{
  items_reset: number; cache_directories_removed: number; backup_path: string; warning: string | null
}> {
  return apiRequest('/api/v1/library/reset-analysis', {
    method: 'POST', body: JSON.stringify({ confirm: 'CLEAR_ALL_LIBRARY_ANALYSIS' }),
  })
}

export function getVideoIndexResults(
  videoId: string, source: IndexSource, limit = 20, offset = 0,
): Promise<IndexResultsPage> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  return apiRequest<IndexResultsPage>(
    `/api/v1/videos/${encodeURIComponent(videoId)}/index-results/${source}?${query.toString()}`,
  )
}

export function getSegmentAnnotation(segmentId: string): Promise<SemanticAnnotation> {
  return apiRequest<SemanticAnnotation>(
    `/api/v1/library/segments/${encodeURIComponent(segmentId)}/annotation`,
  )
}

export function updateSegmentAnnotation(
  segmentId: string,
  input: UpdateAnnotationInput,
): Promise<AnnotationCorrectionResponse> {
  return apiRequest<AnnotationCorrectionResponse>(
    `/api/v1/library/segments/${encodeURIComponent(segmentId)}/annotation`,
    { method: 'PATCH', body: JSON.stringify(input) },
  )
}
