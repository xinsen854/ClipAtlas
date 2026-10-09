import { apiRequest } from './client'

export type StoryRole = 'hook' | 'setup' | 'development' | 'reversal' | 'payoff' | 'ending' | 'other'
export type StoryEvidenceKind = 'visual' | 'asr' | 'ocr'

export type StoryReadiness = {
  project_id: string
  ready: boolean
  video_count: number
  evidence_count: number
  visual_count: number
  asr_count: number
  ocr_count: number
  warnings: string[]
  message: string
}

export type StoryEvidenceReference = {
  evidence_id: string
  kind: StoryEvidenceKind
  video_id: string
  segment_id: string | null
  start_ms: number
  end_ms: number
  text: string
  source_name: string
}

export type StoryOutlineNode = {
  id: string
  order: number
  title: string
  summary: string
  role: StoryRole
  estimated_duration_ms: number
  evidence: StoryEvidenceReference[]
}

export type StoryOutline = {
  id: string
  project_id: string
  revision: number
  skill_name: string
  skill_hash: string
  summary: string
  hook_rationale: string
  nodes: StoryOutlineNode[]
  warnings: string[]
  status: 'draft' | 'confirmed'
  created_at: string
  confirmed_at: string | null
}

export type StoryOutlineEditNode = Pick<
  StoryOutlineNode,
  'id' | 'title' | 'summary' | 'role' | 'estimated_duration_ms'
>

export function getAutoDirectorReadiness(projectId: string): Promise<StoryReadiness> {
  return apiRequest<StoryReadiness>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/auto-director/readiness`,
  )
}

export type AnalyzeStoryInput = {
  projectId: string
  skillName: string
  skillContent: string
}

export function analyzeStory(input: AnalyzeStoryInput): Promise<StoryOutline> {
  return apiRequest<StoryOutline>('/api/v1/auto-director/analyze', {
    method: 'POST',
    body: JSON.stringify({
      project_id: input.projectId,
      skill_name: input.skillName,
      skill_content: input.skillContent,
    }),
  })
}

export function listStoryOutlines(projectId: string): Promise<StoryOutline[]> {
  return apiRequest<StoryOutline[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/auto-director/outlines`,
  )
}

export type UpdateStoryOutlineInput = {
  projectId: string
  outlineId: string
  summary: string
  hookRationale: string
  nodes: StoryOutlineEditNode[]
}

export function updateStoryOutline(input: UpdateStoryOutlineInput): Promise<StoryOutline> {
  return apiRequest<StoryOutline>(
    `/api/v1/auto-director/outlines/${encodeURIComponent(input.outlineId)}`,
    {
      method: 'PUT',
      body: JSON.stringify({
        project_id: input.projectId,
        summary: input.summary,
        hook_rationale: input.hookRationale,
        nodes: input.nodes,
      }),
    },
  )
}

export type ConfirmStoryOutlineInput = {
  projectId: string
  outlineId: string
}

export function confirmStoryOutline(input: ConfirmStoryOutlineInput): Promise<StoryOutline> {
  return apiRequest<StoryOutline>(
    `/api/v1/auto-director/outlines/${encodeURIComponent(input.outlineId)}/confirm`,
    {
      method: 'POST',
      body: JSON.stringify({ project_id: input.projectId }),
    },
  )
}
