import { apiRequest } from './client'
import type { NarrationTrackResponse } from './speech'
import type { RoughCutPlan } from './roughCut'

export type BatchAudioFile = { name: string; size: number }
export type BatchScript = { id: string; code: string | null; title: string; text: string }
export type BatchMatch = { script: BatchScript; audio_index: number | null; reason: string; candidates: number[] }
export type BatchEntry = BatchScript & {
  audio_name: string; audio_size: number; narration_track_id: string | null
  duration_ms: number | null; plan_id: string | null; last_error: string | null
}
export type NarrationBatch = {
  id: string; project_id: string; name: string; top_k: number; export_ratio?: string; entries: BatchEntry[]
  assignment_revision?: number; assignment_order?: string[]
  created_at: string; updated_at: string
}
export type BatchSummary = { id: string; project_id: string; name: string; entry_count: number; created_at: string }

const base = (projectId: string) => `/api/v1/projects/${encodeURIComponent(projectId)}/narration-batches`

export function previewNarrationBatch(projectId: string, markdown: string, files: BatchAudioFile[]): Promise<BatchMatch[]> {
  return apiRequest(`${base(projectId)}/preview`, { method: 'POST', body: JSON.stringify({ markdown, files }) })
}
export function createNarrationBatch(projectId: string, input: {
  name: string; markdown: string; files: BatchAudioFile[]; top_k: number; export_ratio?: string
  assignments: { entry_id: string; audio_index: number }[]
}): Promise<NarrationBatch> {
  return apiRequest(base(projectId), { method: 'POST', body: JSON.stringify({ ...input, confirm: 'MATCHES_CONFIRMED' }) })
}
export function listNarrationBatches(projectId: string, offset = 0): Promise<BatchSummary[]> {
  return apiRequest(`${base(projectId)}?limit=20&offset=${offset}`)
}
export function getNarrationBatch(projectId: string, batchId: string): Promise<NarrationBatch> {
  return apiRequest(`${base(projectId)}/${encodeURIComponent(batchId)}`)
}
export function importBatchAudio(projectId: string, batchId: string, entryId: string, file: File): Promise<NarrationTrackResponse> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest(`${base(projectId)}/${encodeURIComponent(batchId)}/entries/${encodeURIComponent(entryId)}/audio`, { method: 'POST', body: form })
}
export function generateBatchPlan(projectId: string, batchId: string, entryId: string): Promise<RoughCutPlan> {
  return apiRequest(`${base(projectId)}/${encodeURIComponent(batchId)}/entries/${encodeURIComponent(entryId)}/plan`, {
    method: 'POST', body: JSON.stringify({ confirm: 'GENERATE_ROUGH_CUT' }),
  })
}

export function generateBatchPlans(projectId: string, batchId: string): Promise<RoughCutPlan[]> {
  return apiRequest(`${base(projectId)}/${encodeURIComponent(batchId)}/plans`, {
    method: 'POST', body: JSON.stringify({ confirm: 'GENERATE_BATCH_ROUGH_CUT' }),
  })
}
