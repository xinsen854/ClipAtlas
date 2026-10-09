import { apiRequest } from './client'

type LocalActionResponse = {
  action: string
  path: string
}

export function openExportFolder(planId: string): Promise<{ status: 'opened' }> {
  return apiRequest<LocalActionResponse>('/api/v1/system/open-export-folder', {
    method: 'POST',
    body: JSON.stringify({ plan_id: planId }),
  }).then(() => ({ status: 'opened' as const }))
}

export function openJianying(): Promise<{ status: 'launched' }> {
  return apiRequest<LocalActionResponse>('/api/v1/system/open-jianying', {
    method: 'POST',
  }).then(() => ({ status: 'launched' as const }))
}

type PickPathResponse = {
  path: string | null
  cancelled: boolean
}

export function pickDirectory(): Promise<string | null> {
  return apiRequest<PickPathResponse>('/api/v1/system/pick-directory', {
    method: 'POST',
  }).then((response) => (response.cancelled ? null : response.path))
}

export function pickFile(): Promise<string | null> {
  return apiRequest<PickPathResponse>('/api/v1/system/pick-file', {
    method: 'POST',
  }).then((response) => (response.cancelled ? null : response.path))
}

export type LogLine = { level: string; text: string; important: boolean }
export type LogsResponse = { lines: LogLine[]; path: string | null }

export function getLogs(lines = 300): Promise<LogsResponse> {
  return apiRequest<LogsResponse>(`/api/v1/system/logs?lines=${lines}`)
}

