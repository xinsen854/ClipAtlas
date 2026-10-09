import { apiRequest } from './client'

export type RuleKind =
  | 'pronunciation'
  | 'speech_suppress'
  | 'speech_replace'
  | 'subtitle_replace'
  | 'entity_alias'
  | 'semantic_hint'

export type RulePackStatus = 'draft' | 'active'

export type ProjectRule = {
  kind: RuleKind
  match?: string | null
  replacement?: string | null
  hint?: string | null
  enabled: boolean
}

export type ProjectRulePack = {
  project_id: string
  revision: number
  status: RulePackStatus
  rules: ProjectRule[]
}

export type ProjectedText = {
  canonical_text: string
  speech_text: string
  subtitle_text: string
  retrieval_text: string
  semantic_hints: string[]
}

export type RuleAnalysisResult = {
  source_text: string
  rules: ProjectRule[]
}

export type PreviewProjectRulesInput = {
  text: string
  rules: ProjectRule[]
}

function projectRulesPath(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/rules`
}

export function analyzeProjectRules(
  projectId: string,
  text: string,
): Promise<RuleAnalysisResult> {
  return apiRequest<RuleAnalysisResult>(`${projectRulesPath(projectId)}/analyze`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  })
}

export function previewProjectRules(
  projectId: string,
  input: PreviewProjectRulesInput,
): Promise<ProjectedText> {
  return apiRequest<ProjectedText>(`${projectRulesPath(projectId)}/preview`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function saveProjectRuleDraft(
  projectId: string,
  rules: ProjectRule[],
): Promise<ProjectRulePack> {
  return apiRequest<ProjectRulePack>(`${projectRulesPath(projectId)}/drafts`, {
    method: 'POST',
    body: JSON.stringify({ rules }),
  })
}

export function listProjectRulePacks(projectId: string): Promise<ProjectRulePack[]> {
  return apiRequest<ProjectRulePack[]>(projectRulesPath(projectId))
}

export function getActiveProjectRulePack(projectId: string): Promise<ProjectRulePack> {
  return apiRequest<ProjectRulePack>(`${projectRulesPath(projectId)}/active`)
}

export function activateProjectRulePack(
  projectId: string,
  revision: number,
): Promise<ProjectRulePack> {
  return apiRequest<ProjectRulePack>(
    `${projectRulesPath(projectId)}/${encodeURIComponent(String(revision))}/activate`,
    { method: 'POST' },
  )
}
