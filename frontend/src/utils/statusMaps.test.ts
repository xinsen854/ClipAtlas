import { describe, expect, it } from 'vitest'

import { libraryStatusLabels, timingQualityLabels } from './statusMaps'

describe('status label maps', () => {
  it('maps all library processing states to product Chinese', () => {
    expect(libraryStatusLabels).toEqual({
      QUEUED: '等待解析',
      PROBING: '读取视频信息',
      SCENE_DETECTION: '镜头切分',
      FRAME_EXTRACTION: '素材解析中',
      COMPLETED: '解析完成',
      FAILED: '解析失败',
      MISSING: '文件丢失',
    })
  })

  it('maps narration timing authority to Chinese', () => {
    expect(timingQualityLabels).toEqual({
      word_exact: '词级精确',
      unit_exact: '句级精确',
      aligned: '已对齐',
      track_only: '仅总时长',
      estimated: '估算',
    })
  })
})
