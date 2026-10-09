import { apiRequest } from './client'

export type PlannerSettings = {
  top_k: number
  semantic_weight: number
  action_weight: number
  scene_weight: number
  emotion_weight: number
  duration_weight: number
  quality_weight: number
  max_continuity_bonus: number
  continuity_window_ms: number
  reuse_penalty_per_use: number
  max_reuse_penalty: number
}

export type ScriptBeat = {
  id: string
  project_id: string
  narration_track_id: string
  sequence: number
  text: string
  timeline_start_ms: number
  timeline_end_ms: number
  target_duration_ms: number
  query_text: string
  retrieval_intent?: {
    subject?: string
    purpose?: string
    evidence?: 'visual' | 'asr' | 'ocr'
    match_type?: 'direct' | 'supporting'
    visual_queries?: string[]
    keywords?: string[]
    alternatives?: string[]
    visual_requirements?: Record<string, unknown>[]
    candidate_matrix?: Record<string, unknown>[]
  }
}

export type CandidateScore = {
  segment_id: string
  semantic_score: number
  action_score: number
  scene_score: number
  emotion_score: number
  duration_fit_score: number
  quality_score: number
  continuity_bonus: number
  reuse_penalty: number
  total_score: number
}

export type RoughCutClip = {
  beat_id: string
  segment_id: string
  video_id: string
  source_uri: string
  source_in_ms: number
  source_out_ms: number
  timeline_in_ms: number
  timeline_out_ms: number
  score: number
  score_breakdown: CandidateScore
  selection_reason: string
  director_fit?: 'DIRECT' | 'SUPPORT' | 'REJECT' | 'UNKNOWN' | null
  match_level?: 'DIRECT' | 'SUPPORT' | 'RELATED' | 'GENERIC' | null
  director_matched_requirements?: string[]
  director_missing_requirements?: string[]
  evidence_retained?: boolean | null
  evidence_check_reasons?: string[]
  claim_matches?: {
    claim_id: string
    source_quote: string
    importance: 'S' | 'A' | 'B'
    goal: 'proof' | 'related'
    level: 'DIRECT' | 'SUPPORT' | 'UNKNOWN' | 'REJECT'
    evidence_ids: string[]
    evidence_kinds: string[]
    source_ranges: [number, number][]
    matched_conditions: string[]
    missing_conditions: string[]
    reasons: string[]
  }[]
  schedule_level?: 'exact' | 'short' | 'related' | 'text_heavy' | 'generic' | 'source' | 'reuse' | 'c_tail'
  protocol_candidate_type?: string | null
  protocol_id?: string | null
  continuity_status?: string | null
}

export type RoughCutPlan = {
  id: string
  project_id: string
  narration_track_id: string
  narration_revision: number
  revision: number
  total_duration_ms: number
  settings: PlannerSettings
  beats: ScriptBeat[]
  clips: RoughCutClip[]
  warnings?: string[]
  quality_report?: {
    status: 'needs_review'
    timeline_coverage: number
    auto_direct_duration_ratio: number
    auto_s_direct_duration_ratio: number | null
    auto_s_claim_direct_ratio?: number | null
    auto_effective_claim_ratio?: number | null
    human_s_accuracy: number | null
    human_effective_accuracy: number | null
    accuracy_targets_verified: boolean
    one_shot_beat_ratio: number
    short_clip_count: number
    repeated_source_ms: number
    batch_repeated_source_ms: number
    pollution_counts: Record<string, number>
    source_return_count: number
    claim_counts?: Record<'DIRECT' | 'SUPPORT' | 'UNKNOWN' | 'REJECT', number>
  } | null
  protocol_version?: string
  retrieval_protocol_version?: string
  created_at: string
}

export type CreateRoughCutInput = {
  project_id: string
  top_k?: number
  video_ids?: string[] | null
  story_outline_id?: string
  voice_strategy?: 'original_audio' | 'tts'
  speech_profile_id?: string
}

export function createRoughCutPlan(input: CreateRoughCutInput): Promise<RoughCutPlan> {
  return apiRequest<RoughCutPlan>('/api/v1/rough-cut/plans', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function listProjectRoughCutPlans(projectId: string): Promise<RoughCutPlan[]> {
  return apiRequest<RoughCutPlan[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/rough-cut/plans`,
  )
}

export function getActiveRoughCutPlan(projectId: string): Promise<RoughCutPlan> {
  const query = new URLSearchParams({ project_id: projectId })
  return apiRequest<RoughCutPlan>(`/api/v1/rough-cut/plans/active?${query.toString()}`)
}

export function getRoughCutPlan(planId: string): Promise<RoughCutPlan> {
  return apiRequest<RoughCutPlan>(`/api/v1/rough-cut/plans/${encodeURIComponent(planId)}`)
}
