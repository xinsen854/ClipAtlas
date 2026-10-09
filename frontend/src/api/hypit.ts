import { apiRequest } from './client'
import { apiPath } from './lanConnection'

export type HypitConfig = {
  distribution_root: string
  workspace: string
  run_file: string
  endpoint: string
  provider_package: string
  base_url: string | null
  base_url_field: string
  credential_field: string
  provider_config: Record<string, unknown>
  api_key_configured: boolean
}

export type HypitConfigUpdate = Omit<HypitConfig, 'api_key_configured'> & {
  api_key?: string
  clear_api_key?: boolean
}

export type HypitStatus = {
  configured: boolean
  running: boolean
  url: string | null
  pid: number | null
  version: string
  commit: string
}

export type HypitReference = {
  name: string
  size: number
  modified_at: string
}

export type HypitInput = HypitReference & { kind: 'people' | 'products' | 'audio' }

export type HypitBuild = {
  id: string
  created_at: string | null
  title: string | null
  outcome: string
  targets: string[]
  output_count: number
}

export function getHypitConfig(): Promise<HypitConfig> {
  return apiRequest<HypitConfig>('/api/v1/hypit/config')
}

export function updateHypitConfig(input: HypitConfigUpdate): Promise<HypitConfig> {
  return apiRequest<HypitConfig>('/api/v1/hypit/config', {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}

export function testHypitConnection(input: {
  api_key?: string
  provider_package?: string
  base_url?: string
}): Promise<{ ok: boolean; message: string }> {
  return apiRequest<{ ok: boolean; message: string }>('/api/v1/hypit/test-connection', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getHypitStatus(): Promise<HypitStatus> {
  return apiRequest<HypitStatus>('/api/v1/hypit/status')
}

export function startHypit(): Promise<HypitStatus> {
  return apiRequest<HypitStatus>('/api/v1/hypit/start', { method: 'POST' })
}

export function stopHypit(): Promise<HypitStatus> {
  return apiRequest<HypitStatus>('/api/v1/hypit/stop', { method: 'POST' })
}

export function listHypitReferences(): Promise<HypitReference[]> {
  return apiRequest<HypitReference[]>('/api/v1/hypit/references')
}

export function uploadHypitReference(file: File): Promise<HypitReference> {
  const body = new FormData()
  body.append('file', file)
  return apiRequest<HypitReference>('/api/v1/hypit/references', { method: 'POST', body })
}

export function deleteHypitReference(name: string): Promise<void> {
  return apiRequest<void>(`/api/v1/hypit/references/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
}

export function listHypitInputs(): Promise<HypitInput[]> {
  return apiRequest<HypitInput[]>('/api/v1/hypit/inputs')
}

export function uploadHypitInput(kind: HypitInput['kind'], file: File): Promise<HypitInput> {
  const body = new FormData()
  body.append('file', file)
  return apiRequest<HypitInput>(`/api/v1/hypit/inputs?kind=${encodeURIComponent(kind)}`, { method: 'POST', body })
}

export function getHypitBrief(): Promise<{ text: string }> {
  return apiRequest<{ text: string }>('/api/v1/hypit/brief')
}

export function updateHypitBrief(text: string): Promise<{ text: string }> {
  return apiRequest<{ text: string }>('/api/v1/hypit/brief', {
    method: 'PUT',
    body: JSON.stringify({ text }),
  })
}

export function listHypitBuilds(): Promise<HypitBuild[]> {
  return apiRequest<HypitBuild[]>('/api/v1/hypit/builds')
}

export function submitHypitBuild(title?: string): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>('/api/v1/hypit/builds', {
    method: 'POST',
    body: JSON.stringify({ title: title?.trim() || null }),
  })
}

export function updateHypitBuildTitle(buildId: string, title: string): Promise<void> {
  return apiRequest<void>(`/api/v1/hypit/builds/${encodeURIComponent(buildId)}/title`, {
    method: 'PUT',
    body: JSON.stringify({ title }),
  })
}

export function hypitOutputUrl(buildId: string, output: string): string {
  return apiPath(
    `/api/v1/hypit/builds/${encodeURIComponent(buildId)}/outputs/${encodeURIComponent(output)}`,
  )
}

export function openHypitOutput(buildId: string, output: string): Promise<{ action: string; path: string }> {
  return apiRequest<{ action: string; path: string }>(
    `/api/v1/hypit/builds/${encodeURIComponent(buildId)}/outputs/${encodeURIComponent(output)}/open`,
    { method: 'POST' },
  )
}

export async function downloadHypitOutput(
  buildId: string,
  output: string,
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(hypitOutputUrl(buildId, output), { headers: { Accept: '*/*' } })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `导出失败（HTTP ${response.status}）`)
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  const filename = encoded ? decodeURIComponent(encoded) : plain || (output === 'final.video' ? 'final.mp4' : output)
  return { blob: await response.blob(), filename }
}
