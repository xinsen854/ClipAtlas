import { apiRequest } from './client'

export type SettingSource = 'environment' | 'file' | 'default'
export type JianyingModeSetting = 'portable' | 'jianying_pro_10_8'
export type SettingsServiceKind = 'video' | 'embedding' | 'speech'
export type BailianModelStatus = 'available' | 'unavailable' | 'undetected'

export type PublicSettingValue = {
  value: string | number | null
  source: SettingSource
}

export type PublicSettings = {
  library_provider: PublicSettingValue
  bailian_base_url: PublicSettingValue
  qwen_base_url: PublicSettingValue
  qwen_default_model: PublicSettingValue
  qwen_long_context_model: PublicSettingValue
  embedding_base_url: PublicSettingValue
  embedding_model: PublicSettingValue
  embedding_dimensions: PublicSettingValue
  speech_provider: PublicSettingValue
  speech_base_url: PublicSettingValue
  speech_model: PublicSettingValue
  jianying_draft_root: PublicSettingValue
  jianying_install_dir: PublicSettingValue
  jianying_user_data: PublicSettingValue
  jianying_mode: PublicSettingValue
  jianying_executable: PublicSettingValue
  bailian_api_key_configured: boolean
  bailian_api_key_source: SettingSource
  qwen_api_key_configured: boolean
  qwen_api_key_source: SettingSource
  embedding_api_key_configured: boolean
  embedding_api_key_source: SettingSource
  speech_api_key_configured: boolean
  speech_api_key_source: SettingSource
}

export type SettingsPatch = {
  library_provider?: string | null
  bailian_api_key?: string | null
  bailian_base_url?: string | null
  qwen_api_key?: string | null
  qwen_base_url?: string | null
  qwen_default_model?: string | null
  qwen_long_context_model?: string | null
  embedding_api_key?: string | null
  embedding_base_url?: string | null
  embedding_model?: string | null
  embedding_dimensions?: number | null
  speech_provider?: string | null
  speech_api_key?: string | null
  speech_base_url?: string | null
  speech_model?: string | null
  jianying_draft_root?: string | null
  jianying_install_dir?: string | null
  jianying_user_data?: string | null
  jianying_mode?: JianyingModeSetting | null
  jianying_executable?: string | null
  clear_bailian_api_key?: boolean
  clear_qwen_api_key?: boolean
  clear_embedding_api_key?: boolean
  clear_speech_api_key?: boolean
}

export type UpdateSettingsResponse = {
  settings: PublicSettings
  restart_required: boolean
}

export type ProbeSettingsInput = {
  service: SettingsServiceKind
  provider: string
  api_key?: string | null
  base_url: string
  model: string
  dimensions?: number | null
}

export type ProbeConnectionResponse = {
  ok: boolean
  code: string
  message: string
}

export type BailianModelDetectionInput = {
  api_key?: string | null
  base_url: string
}

export type BailianModelDetectionResponse = {
  ok: boolean
  code: string
  message: string
  models: Record<string, BailianModelStatus>
}

export function getSettings(): Promise<PublicSettings> {
  return apiRequest<PublicSettings>('/api/v1/settings')
}

export function updateSettings(input: SettingsPatch): Promise<UpdateSettingsResponse> {
  return apiRequest<UpdateSettingsResponse>('/api/v1/settings', {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function testSettingsConnection(
  input: ProbeSettingsInput,
): Promise<ProbeConnectionResponse> {
  return apiRequest<ProbeConnectionResponse>('/api/v1/settings/test-connection', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function detectBailianModels(
  input: BailianModelDetectionInput,
): Promise<BailianModelDetectionResponse> {
  return apiRequest<BailianModelDetectionResponse>('/api/v1/settings/bailian/models', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
