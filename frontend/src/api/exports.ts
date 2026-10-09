import { apiRequest } from './client'

export type OtioExportArtifact = {
  plan_id: string
  project_id: string
  narration_track_id: string
  output_path: string
  total_duration_ms: number
  timing_rate: number
  rough_cut_revision: number
  narration_revision: number
  created_at: string
}

export type JianyingMode = 'portable' | 'jianying_pro_10_8'

export type JianyingDraftArtifact = {
  plan_id: string
  project_id: string
  narration_track_id: string
  draft_name: string
  output_path: string
  mode: JianyingMode
  backend_name: string
  backend_version: string
  total_duration_ms: number
  created_at: string
}

export type ExportJianyingInput = {
  plan_id: string
  draft_name?: string
  width?: number
  height?: number
}

export function exportOtio(planId: string): Promise<OtioExportArtifact> {
  return apiRequest<OtioExportArtifact>('/api/v1/exports/otio', {
    method: 'POST',
    body: JSON.stringify({ plan_id: planId }),
  })
}

export function exportJianying(input: ExportJianyingInput): Promise<JianyingDraftArtifact> {
  return apiRequest<JianyingDraftArtifact>('/api/v1/exports/jianying', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
