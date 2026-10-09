import { describe, expect, it } from 'vitest'

import { toAnnotationUpdateInput } from './AnnotationEditor'

describe('annotation editor payload', () => {
  it('preserves every editable annotation field including lock state', () => {
    expect(
      toAnnotationUpdateInput({
        description: '雨夜街口，一名女子撑伞等待。',
        characters: ['女子'],
        actions: ['撑伞', '等待'],
        scene: ['雨夜', '街口'],
        emotions: ['克制', '焦虑'],
        objects: ['雨伞'],
        ocr: ['公交站'],
        shot_type: '中景',
        camera_motion: '固定',
        confidence: 0.82,
        locked: false,
      }),
    ).toEqual({
      description: '雨夜街口，一名女子撑伞等待。',
      characters: ['女子'],
      actions: ['撑伞', '等待'],
      scene: ['雨夜', '街口'],
      emotions: ['克制', '焦虑'],
      objects: ['雨伞'],
      ocr: ['公交站'],
      shot_type: '中景',
      camera_motion: '固定',
      confidence: 0.82,
      locked: false,
    })
  })
})
