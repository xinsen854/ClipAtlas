export const libraryStatusLabels = {
  QUEUED: '等待解析',
  PROBING: '读取视频信息',
  SCENE_DETECTION: '镜头切分',
  FRAME_EXTRACTION: '素材解析中',
  COMPLETED: '解析完成',
  FAILED: '解析失败',
  MISSING: '文件丢失',
} as const

export const timingQualityLabels = {
  word_exact: '词级精确',
  unit_exact: '句级精确',
  aligned: '已对齐',
  track_only: '仅总时长',
  estimated: '估算',
} as const

export type LibraryItemStatus = keyof typeof libraryStatusLabels
export type TimingQuality = keyof typeof timingQualityLabels

export function isLibraryItemPending(status: LibraryItemStatus | undefined): boolean {
  return status !== undefined && ['QUEUED', 'PROBING', 'SCENE_DETECTION', 'FRAME_EXTRACTION'].includes(status)
}
