import { apiRequest } from './client'
import type { TimingQuality } from '../utils/statusMaps'

export type VoiceGender = 'male' | 'female' | 'neutral' | 'unknown' | 'unrestricted'
export type AgeStyle = 'youth' | 'young' | 'mature' | 'elderly' | 'unknown' | 'unrestricted'
export type RandomMode = 'none' | 'random_voice' | 'random_parameters' | 'random_all'
export type NarrationSourceMode = 'tts' | 'imported' | 'estimated'

export type SpeechProviderCapabilities = {
  preset_voices: boolean
  voice_metadata: boolean
  speed_control: boolean
  pitch_control: boolean
  volume_control: boolean
  emotion_control: boolean
  instruction_control: boolean
  voice_clone: boolean
  voice_design: boolean
  word_timestamps: boolean
  streaming: boolean
  languages: string[]
}

export type SpeechProviderDescriptor = {
  name: string
  model: string
  capabilities: SpeechProviderCapabilities
}

export type VoiceDescriptor = {
  provider: string
  voice_id: string
  display_name: string
  gender: VoiceGender
  age_style: AgeStyle
  languages: string[]
  accents: string[]
  tags: string[]
  preview_uri: string | null
  capability_overrides: Record<string, boolean>
}

export type SpeechProfile = {
  id: string
  project_id: string
  provider: string
  model: string
  voice_id: string
  gender_constraint: VoiceGender | null
  age_style_constraint: AgeStyle | null
  language: string | null
  accent: string | null
  speed: number | null
  pitch: number | null
  volume: number | null
  emotion: string | null
  style: string | null
  instruction: string | null
  random_seed: number | null
  random_mode: RandomMode
  locked: boolean
  revision: number
  created_at: string
}

export type NarrationTrack = {
  id: string
  project_id: string
  source_mode: NarrationSourceMode
  script_hash: string
  speech_profile_id: string | null
  provider: string | null
  model: string | null
  audio_uri: string | null
  duration_ms: number
  timing_quality: TimingQuality
  revision: number
  created_at: string
}

export type NarrationUnit = {
  id: string
  track_id: string
  sequence: number
  text: string
  text_hash: string
  start_ms: number | null
  end_ms: number | null
  source: NarrationSourceMode
  audio_uri: string | null
  created_at: string
}

export type NarrationWordTiming = {
  unit_id: string
  sequence: number
  word: string
  start_ms: number
  end_ms: number
  confidence: number | null
}

export type NarrationTrackResponse = {
  track: NarrationTrack
  units: NarrationUnit[]
  word_timings: NarrationWordTiming[]
  script?: string
}

export type ProjectScript = {
  project_id: string
  text: string
  script_hash: string
  updated_at: string | null
}

export function getProjectScript(projectId: string): Promise<ProjectScript> {
  return apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/script`)
}

export function saveProjectScript(projectId: string, text: string): Promise<{
  script: ProjectScript; attached_track_id: string | null
}> {
  return apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/script`, {
    method: 'PUT', body: JSON.stringify({ text, attach_to_active_narration: true }),
  })
}

export type ProjectNarrationHistoryResponse = {
  tracks: NarrationTrack[]
  active_track_id: string | null
}

export type VoiceConstraints = {
  gender?: VoiceGender | null
  age_style?: AgeStyle | null
  language?: string | null
  accent?: string | null
  tags?: string[]
}

export type CreateSpeechProfileInput = {
  project_id: string
  provider: string
  voice_id: string
  gender_constraint?: VoiceGender | null
  age_style_constraint?: AgeStyle | null
  language?: string | null
  accent?: string | null
  speed?: number | null
  pitch?: number | null
  volume?: number | null
  emotion?: string | null
  style?: string | null
  instruction?: string | null
  locked?: boolean
}

export type UpdateSpeechProfileInput = Omit<Partial<CreateSpeechProfileInput>, 'project_id'>

export type RandomizeSpeechProfileInput = {
  project_id: string
  provider: string
  mode?: RandomMode
  seed: number
  constraints?: VoiceConstraints
  voice_id?: string | null
}

export type CreateTtsInput = {
  project_id: string
  script: string
  speech_profile_id: string
}

export function listSpeechProviders(): Promise<SpeechProviderDescriptor[]> {
  return apiRequest<SpeechProviderDescriptor[]>('/api/v1/speech/providers')
}

export function listSpeechVoices(provider: string): Promise<VoiceDescriptor[]> {
  return apiRequest<VoiceDescriptor[]>(
    `/api/v1/speech/providers/${encodeURIComponent(provider)}/voices`,
  )
}

export function listProjectSpeechProfiles(projectId: string): Promise<SpeechProfile[]> {
  return apiRequest<SpeechProfile[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/speech-profiles`,
  )
}

export function listProjectNarrations(projectId: string): Promise<ProjectNarrationHistoryResponse> {
  return apiRequest<ProjectNarrationHistoryResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/narrations`,
  )
}

export function createSpeechProfile(input: CreateSpeechProfileInput): Promise<SpeechProfile> {
  return apiRequest<SpeechProfile>('/api/v1/speech/profiles', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updateSpeechProfile(
  profileId: string,
  input: UpdateSpeechProfileInput,
): Promise<SpeechProfile> {
  return apiRequest<SpeechProfile>(`/api/v1/speech/profiles/${encodeURIComponent(profileId)}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function randomizeSpeechProfile(input: RandomizeSpeechProfileInput): Promise<SpeechProfile> {
  return apiRequest<SpeechProfile>('/api/v1/speech/profiles/randomize', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function createTtsNarration(input: CreateTtsInput): Promise<NarrationTrackResponse> {
  return apiRequest<NarrationTrackResponse>('/api/v1/narration/tts', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function importNarration(input: {
  projectId: string
  script: string
  file: File
}): Promise<NarrationTrackResponse> {
  const body = new FormData()
  body.append('project_id', input.projectId)
  body.append('script', input.script)
  body.append('file', input.file)
  return apiRequest<NarrationTrackResponse>('/api/v1/narration/import', {
    method: 'POST',
    body,
  })
}

export function getNarrationTrack(trackId: string): Promise<NarrationTrackResponse> {
  return apiRequest<NarrationTrackResponse>(`/api/v1/narration/${encodeURIComponent(trackId)}`)
}

export function activateNarrationTrack(trackId: string): Promise<NarrationTrackResponse> {
  return apiRequest<NarrationTrackResponse>(
    `/api/v1/narration/${encodeURIComponent(trackId)}/activate`,
    { method: 'POST' },
  )
}
