import { describe, expect, it } from 'vitest'

import { toSpeechProfileInput } from './SpeechProfileForm'

describe('speech profile form payload', () => {
  it('preserves provider voice and all manual speech controls', () => {
    expect(
      toSpeechProfileInput('project-1', {
        provider: 'dashscope',
        voice_id: 'custom-voice-007',
        gender_constraint: 'female',
        age_style_constraint: 'mature',
        language: 'zh',
        accent: '普通话',
        speed: 1.15,
        pitch: -1,
        volume: 0.9,
        emotion: '克制',
        style: '纪录片',
        instruction: '语气沉稳，不要夸张',
        locked: true,
      }),
    ).toEqual({
      project_id: 'project-1',
      provider: 'dashscope',
      voice_id: 'custom-voice-007',
      gender_constraint: 'female',
      age_style_constraint: 'mature',
      language: 'zh',
      accent: '普通话',
      speed: 1.15,
      pitch: -1,
      volume: 0.9,
      emotion: '克制',
      style: '纪录片',
      instruction: '语气沉稳，不要夸张',
      locked: true,
    })
  })
})
