import { apiRequest } from './client'

export type HealthResponse = {
  status: string
  service: string
  version: string
}

export function getHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/health')
}
