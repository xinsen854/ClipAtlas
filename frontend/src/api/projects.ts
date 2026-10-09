import { apiRequest } from './client'

export type Project = {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export type CreateProjectInput = {
  name: string
  description?: string | null
}

export type UpdateProjectInput = {
  name?: string
  description?: string | null
}

export function listProjects(): Promise<Project[]> {
  return apiRequest<Project[]>('/api/v1/projects')
}

export function createProject(input: CreateProjectInput): Promise<Project> {
  return apiRequest<Project>('/api/v1/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getProject(projectId: string): Promise<Project> {
  return apiRequest<Project>(`/api/v1/projects/${encodeURIComponent(projectId)}`)
}

export function updateProject(projectId: string, input: UpdateProjectInput): Promise<Project> {
  return apiRequest<Project>(`/api/v1/projects/${encodeURIComponent(projectId)}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export type ProjectDeletionPreview = {
  project_id: string; name: string; narrations: number; plans: number; batches: number
  directories: string[]; warnings: string[]
}

export function getProjectDeletionPreview(id: string): Promise<ProjectDeletionPreview> {
  return apiRequest(`/api/v1/projects/${encodeURIComponent(id)}/deletion-preview`)
}

export function deleteProject(id: string): Promise<ProjectDeletionPreview & { backup_directory: string }> {
  return apiRequest(`/api/v1/projects/${encodeURIComponent(id)}`, {
    method: 'DELETE', body: JSON.stringify({ confirm: 'DELETE_PROJECT' }),
  })
}
