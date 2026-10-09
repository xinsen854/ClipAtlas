export type CandidateDisplayLevel =
  | 'S'
  | 'A'
  | 'B'
  | 'Generic'
  | 'Fallback/Source'
  | 'Fallback/Reuse'

export type TimelineClip = {
  id: string
  source_id: string
  source_path: string
  timeline_start_ms: number
  duration_ms: number
  source_in_ms: number
  source_out_ms: number
  opacity: number
  volume: number
  transform: Record<string, number>
  effects: Record<string, unknown>[]
}

export type TimelineTrack = {
  id: string
  kind: 'video' | 'audio' | 'text' | 'overlay'
  clips: TimelineClip[]
}

export type TimelineDocument = {
  version: number
  project_id: string
  source_plan_id: string
  width: number
  height: number
  fps: number
  duration_ms: number
  tracks: TimelineTrack[]
}

export type CandidateItem = {
  requirement_id: string
  sentence_id: string | null
  source_quote: string | null
  importance: string | null
  candidate_type: string
  candidate_id: string | null
  media_id: string
  source_in_ms: number
  source_out_ms: number
  anchor_in_ms: number | null
  anchor_out_ms: number | null
  continuity_status: string | null
  display_level: CandidateDisplayLevel
  pollution_level: string | null
  visual_family: string | null
  presentation_type: string | null
  subject_score: number
  action_score: number
  scene_score: number
  environment_score: number
  object_score: number
  configuration_score: number
  quantity_score: number
  relation_score: number
  order_score: number
  vector_score: number
  preliminary_level: string
}

export type CandidateList = {
  context_id: string
  items: CandidateItem[]
}

export type MediaReference = {
  media_id: string
  source_uri: string
}

export type NarrationSegmentReference = {
  id: string
  text: string
  start_ms: number
  end_ms: number
}

export type NarrationReference = {
  track_id: string
  revision: number
  audio_uri: string | null
  duration_ms: number
  segments: NarrationSegmentReference[]
}
