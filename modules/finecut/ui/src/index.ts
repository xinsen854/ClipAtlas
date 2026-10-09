import type {
  CandidateItem,
  CandidateList,
  MediaReference,
  NarrationReference,
  NarrationSegmentReference,
  TimelineClip,
  TimelineDocument,
} from './contracts'

export const fineCutUiAvailable = true

export type FineCutMountOptions = {
  planId: string
}

type PreviewStatus = 'gap' | 'resolving' | 'ready' | 'unresolved' | 'error'
type PresentationMarker = CandidateItem['display_level']

type ClipPropertyUpdate = {
  opacity?: number
  volume?: number
  transform?: Record<string, number>
}

type JianyingDraftArtifact = {
  draft_name: string
  output_path: string
}

const DISPLAY_LEVELS = new Set([
  'S',
  'A',
  'B',
  'Generic',
  'Fallback/Source',
  'Fallback/Reuse',
])

const NORMAL_LEVELS = ['S', 'A', 'B', 'Generic'] as const
const ZOOM_LEVELS = [40, 80, 120, 160] as const
const DEFAULT_ZOOM_INDEX = 1
const SNAP_THRESHOLD_PX = 8
const TIMELINE_SCROLL_MARGIN_PX = 24

const STYLE = `
.finecut-root{font-family:Inter,"Microsoft YaHei",sans-serif;color:#1f2329;background:#f5f6f8;min-height:100%;padding:16px;box-sizing:border-box}
.finecut-header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:0 0 14px}.finecut-title{font-size:20px;font-weight:700;margin:0}.finecut-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.finecut-action{border:1px solid #d0d5dd;background:#fff;border-radius:7px;padding:6px 10px;cursor:pointer}.finecut-action:disabled{cursor:not-allowed;opacity:.5}.finecut-notice{font-size:12px;color:#667085}
.finecut-grid{display:grid;grid-template-columns:minmax(260px,32%) 1fr;gap:12px}.finecut-panel{background:#fff;border:1px solid #e7e9ee;border-radius:10px;padding:12px;box-sizing:border-box}.finecut-candidates{max-height:430px;overflow:auto}
.finecut-section{margin:0 0 12px}.finecut-section h3{font-size:14px;margin:0 0 7px}.finecut-card{border:1px solid #e4e7ec;border-radius:8px;padding:9px;margin:0 0 7px;background:#fff}
.finecut-card strong{display:block;margin-bottom:5px}.finecut-meta{font-size:12px;color:#667085;line-height:1.6;word-break:break-all}.finecut-empty{font-size:12px;color:#98a2b3;padding:6px 0}.finecut-replace{margin-top:7px;border:1px solid #1677ff;background:#1677ff;color:#fff;border-radius:6px;padding:5px 8px;cursor:pointer}.finecut-replace:disabled{border-color:#d0d5dd;background:#f2f4f7;color:#98a2b3;cursor:not-allowed}
.finecut-preview{min-height:300px;display:flex;flex-direction:column;justify-content:center;align-items:center;background:#111827;color:#f9fafb;border-radius:8px;text-align:center;padding:20px;box-sizing:border-box;gap:8px;overflow:hidden}
.finecut-preview small{color:#9ca3af}.finecut-preview-video{display:block;width:100%;max-height:260px;background:#000;border-radius:6px;transform-origin:center center}.finecut-preview-controls{display:flex;gap:8px;justify-content:center}.finecut-preview-controls .finecut-action{min-width:72px}.finecut-seek{width:100%;margin-top:12px}.finecut-timeline{grid-column:1 / -1;display:flex;flex-direction:column;gap:8px}
.finecut-effects{grid-column:1 / -1}.finecut-effects-grid{display:grid;grid-template-columns:repeat(6,minmax(100px,1fr));gap:8px;align-items:end}.finecut-effects-field{display:flex;flex-direction:column;gap:4px;font-size:12px;color:#667085}.finecut-effects-input{width:100%;border:1px solid #d0d5dd;border-radius:6px;padding:6px 7px;box-sizing:border-box}.finecut-effects-actions{display:flex;justify-content:flex-end;margin-top:10px}
.finecut-timeline-toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.finecut-zoom{display:flex;align-items:center;gap:6px}.finecut-zoom-value{font-size:12px;color:#667085;min-width:74px;text-align:center}
.finecut-timeline-layout{display:grid;grid-template-columns:120px minmax(0,1fr);gap:10px;align-items:start}.finecut-track-labels{display:grid;grid-template-rows:28px 52px 48px 40px;gap:6px}.finecut-track-label{font-weight:700;font-size:13px;display:flex;align-items:center}.finecut-track-label-spacer{height:28px}.finecut-timeline-scroll{overflow-x:auto;overflow-y:hidden;border:1px solid #e4e7ec;border-radius:8px;background:#fcfcfd}
.finecut-timeline-surface{position:relative;min-height:186px;cursor:crosshair}.finecut-ruler{position:relative;height:28px;border-bottom:1px solid #e4e7ec;background:#f9fafb}.finecut-ruler-tick{position:absolute;top:0;height:100%;border-left:1px solid #d0d5dd;font-size:10px;color:#667085;padding:5px 0 0 4px;box-sizing:border-box;white-space:nowrap}
.finecut-track{position:relative;border-bottom:1px solid #eef0f3}.finecut-track:last-of-type{border-bottom:0}.finecut-track-v1{height:52px}.finecut-track-t1{height:48px}.finecut-track-a1{height:40px}.finecut-track-body{position:absolute;inset:0}
.finecut-clip,.finecut-segment{position:absolute;top:4px;bottom:4px;border:1px solid #d0d5dd;background:#f9fafb;border-radius:7px;padding:5px 7px;cursor:pointer;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;text-align:left;box-sizing:border-box}.finecut-selected{border-color:#1677ff;background:#e6f4ff;box-shadow:inset 0 0 0 1px #1677ff}
.finecut-clip{isolation:isolate}.finecut-clip-thumbnail{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.28;pointer-events:none;z-index:-1}.finecut-clip-content{position:relative;z-index:1;display:flex;align-items:center;gap:6px;min-width:0;height:100%}.finecut-clip-label{font-size:12px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:42%}.finecut-clip-source{font-size:10px;color:#475467;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}.finecut-clip-marker{font-size:9px;font-weight:700;border:1px solid #98a2b3;border-radius:4px;padding:1px 3px;background:rgba(255,255,255,.85);white-space:nowrap}.finecut-clip-missing{font-size:10px;font-weight:700;color:#b42318;background:rgba(255,255,255,.88);border-radius:4px;padding:1px 3px;white-space:nowrap}
.finecut-trim-handle{position:absolute;top:4px;bottom:4px;width:10px;transform:translateX(-5px);z-index:7;border:0;border-radius:3px;background:#1677ff;opacity:.85;padding:0;cursor:ew-resize}.finecut-trim-handle:disabled{opacity:.35;cursor:not-allowed}
.finecut-visual-actions{position:absolute;top:13px;z-index:7;display:flex;gap:3px;transform:translateX(-100%)}.finecut-visual-action{border:1px solid #1677ff;background:#fff;color:#1677ff;border-radius:4px;padding:2px 5px;font-size:11px;line-height:16px;cursor:pointer}.finecut-visual-action:disabled{opacity:.45;cursor:not-allowed}
.finecut-audio{position:absolute;top:4px;bottom:4px;border:1px solid #d0d5dd;background:#f2f4f7;border-radius:7px;padding:5px 8px;font-size:12px;color:#475467;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;box-sizing:border-box}
.finecut-playhead{position:absolute;top:0;bottom:0;width:2px;background:#f04438;z-index:8;cursor:ew-resize;transform:translateX(-1px)}.finecut-playhead::before{content:"";position:absolute;top:0;left:-4px;width:10px;height:10px;background:#f04438;border-radius:2px}.finecut-playhead-hit{position:absolute;top:0;bottom:0;left:-7px;width:16px}
.finecut-edit-controls{display:flex;align-items:center;gap:7px;flex-wrap:wrap;padding:8px 0 2px 130px}.finecut-edit-input{width:90px;border:1px solid #d0d5dd;border-radius:6px;padding:5px 7px}.finecut-edit-label{font-size:12px;color:#667085}
.finecut-fallback summary{cursor:pointer;font-weight:700;font-size:14px;margin-bottom:7px}.finecut-status{padding:24px;text-align:center;color:#667085}.finecut-error{color:#b42318}
@media(max-width:900px){.finecut-grid{grid-template-columns:1fr}.finecut-timeline,.finecut-effects{grid-column:1}.finecut-header{align-items:flex-start;flex-direction:column}.finecut-edit-controls{padding-left:0}.finecut-timeline-layout{grid-template-columns:86px minmax(0,1fr)}.finecut-effects-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}}
`

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text !== undefined) node.textContent = text
  return node
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body != null) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {
      detail?: string
      error?: { message?: string }
    } | null
    throw new Error(payload?.error?.message ?? payload?.detail ?? `请求失败：${response.status}`)
  }
  return response.json() as Promise<T>
}

async function requestOptionalJson<T>(path: string): Promise<T | null> {
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!response.ok) return null
  return response.json() as Promise<T>
}

function formatMs(value: number): string {
  const totalSeconds = Math.max(0, value) / 1000
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds - minutes * 60
  return `${minutes}:${seconds.toFixed(1).padStart(4, '0')}`
}

function timeToPx(valueMs: number, pixelsPerSecond: number): number {
  return Math.max(0, valueMs) * pixelsPerSecond / 1000
}

function clampTimelineMs(value: number, durationMs: number): number {
  return Math.min(Math.max(0, value), durationMs)
}

function timelineSnapTargets(
  timeline: TimelineDocument,
  narration: NarrationReference,
): number[] {
  const targets = new Set<number>([0, timeline.duration_ms])
  timeline.tracks.forEach((track) => {
    track.clips.forEach((clip) => {
      targets.add(clampTimelineMs(clip.timeline_start_ms, timeline.duration_ms))
      targets.add(clampTimelineMs(
        clip.timeline_start_ms + clip.duration_ms,
        timeline.duration_ms,
      ))
    })
  })
  narration.segments.forEach((segment) => {
    targets.add(clampTimelineMs(segment.start_ms, timeline.duration_ms))
    targets.add(clampTimelineMs(segment.end_ms, timeline.duration_ms))
  })
  return Array.from(targets).filter(Number.isFinite).sort((a, b) => a - b)
}

function snapTimelineMs(
  valueMs: number,
  timeline: TimelineDocument,
  narration: NarrationReference,
  pixelsPerSecond: number,
): number {
  const raw = clampTimelineMs(valueMs, timeline.duration_ms)
  if (!(pixelsPerSecond > 0)) return raw
  const thresholdMs = SNAP_THRESHOLD_PX / pixelsPerSecond * 1000
  let best = raw
  let bestDistance = Number.POSITIVE_INFINITY
  timelineSnapTargets(timeline, narration).forEach((target) => {
    const distance = Math.abs(target - raw)
    if (distance < bestDistance || (distance === bestDistance && target < best)) {
      best = target
      bestDistance = distance
    }
  })
  return bestDistance <= thresholdMs ? best : raw
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT'
    || tag === 'TEXTAREA'
    || tag === 'SELECT'
    || target.isContentEditable
    || target.closest('[contenteditable="true"]') != null
}

function segmentAtClipStart(
  narration: NarrationReference | null,
  clip: TimelineClip,
): NarrationSegmentReference | null {
  if (!narration) return null
  return narration.segments.find((segment) =>
    segment.start_ms <= clip.timeline_start_ms && clip.timeline_start_ms < segment.end_ms,
  ) ?? null
}

function visibleCandidate(item: CandidateItem): boolean {
  if (!DISPLAY_LEVELS.has(String(item.display_level))) return false
  if (String(item.pollution_level ?? '').toLowerCase() === 'blocked') return false
  return item.source_in_ms >= 0 && item.source_out_ms > item.source_in_ms
}

function findSelectedClip(timeline: TimelineDocument | null, clipId: string | null): TimelineClip | null {
  if (!timeline || !clipId) return null
  for (const track of timeline.tracks) {
    const clip = track.clips.find((item) => item.id === clipId)
    if (clip) return clip
  }
  return null
}

function findActiveVideoClip(timeline: TimelineDocument | null, playheadMs: number): TimelineClip | null {
  if (!timeline) return null
  const videoTrack = timeline.tracks.find((track) => track.kind === 'video')
  return videoTrack?.clips.find((clip) =>
    clip.timeline_start_ms <= playheadMs
      && playheadMs < clip.timeline_start_ms + clip.duration_ms,
  ) ?? null
}

function sourceTimeSeconds(clip: TimelineClip, playheadMs: number): number {
  const offset = clampTimelineMs(
    playheadMs - clip.timeline_start_ms,
    clip.duration_ms,
  )
  const sourceMs = Math.min(clip.source_out_ms, clip.source_in_ms + offset)
  return sourceMs / 1000
}

function candidateFitsClip(candidate: CandidateItem, clip: TimelineClip): boolean {
  return candidate.source_out_ms - candidate.source_in_ms >= clip.duration_ms
}

function transformValue(clip: TimelineClip, key: string, fallback: number): number {
  const value = clip.transform[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function previewTransform(clip: TimelineClip): string {
  const positionX = transformValue(clip, 'position_x', 0)
  const positionY = transformValue(clip, 'position_y', 0)
  const scale = transformValue(clip, 'scale', 1)
  const rotation = transformValue(clip, 'rotation', 0)
  return `translate(${positionX}px, ${positionY}px) scale(${scale}) rotate(${rotation}deg)`
}

function sourceDisplayName(clip: TimelineClip, media: MediaReference | null | undefined): string {
  const source = media?.source_uri || clip.source_path || clip.source_id
  const normalized = source.replace(/\\/g, '/')
  const basename = normalized.split('/').filter(Boolean).at(-1) || clip.source_id
  try {
    return decodeURIComponent(basename)
  } catch {
    return basename
  }
}

function markerLabel(marker: PresentationMarker): string {
  if (marker === 'Fallback/Source') return 'Fallback / Source'
  if (marker === 'Fallback/Reuse') return 'Fallback / Reuse'
  return marker
}

function presentationMarker(
  clip: TimelineClip,
  media: MediaReference | null | undefined,
  narration: NarrationReference,
  candidates: CandidateList | null,
): PresentationMarker | null {
  if (!media) return null
  if (clip.source_id !== media.media_id) return 'Fallback/Source'
  const segment = segmentAtClipStart(narration, clip)
  if (!segment || candidates?.context_id !== segment.id) return null
  const levels = new Set<PresentationMarker>()
  candidates.items.filter(visibleCandidate).forEach((item) => {
    if (
      item.media_id === media.media_id
      && item.source_in_ms <= clip.source_in_ms
      && clip.source_out_ms <= item.source_out_ms
    ) {
      levels.add(item.display_level)
    }
  })
  return levels.size === 1 ? Array.from(levels)[0] : null
}

function clipThumbnail(
  clip: TimelineClip,
  media: MediaReference,
): { key: string; url: string } {
  const timestampMs = Math.floor((clip.source_in_ms + clip.source_out_ms) / 2)
  return {
    key: `${media.media_id}:${timestampMs}`,
    url: `/api/v1/videos/${encodeURIComponent(media.media_id)}/index-thumbnail?timestamp_ms=${timestampMs}`,
  }
}

function appendMeta(card: HTMLElement, label: string, value: string | null | undefined): void {
  if (!value) return
  const line = el('div', 'finecut-meta')
  line.textContent = `${label}：${value}`
  card.append(line)
}

function candidateCard(
  item: CandidateItem,
  selectedClip: TimelineClip | null,
  mediaById: Record<string, MediaReference | null>,
  editBusy: boolean,
  handlers: {
    replaceCandidate: (candidate: CandidateItem) => void
    startCandidateDrag: (candidate: CandidateItem) => void
    endCandidateDrag: () => void
  },
): HTMLElement {
  const card = el('article', 'finecut-card')
  card.dataset.candidateId = item.candidate_id ?? item.requirement_id
  card.append(el('strong', undefined, item.source_quote || item.media_id))
  appendMeta(card, '等级', item.display_level)
  appendMeta(card, '文案重要度', item.importance)
  appendMeta(card, '素材', item.media_id)
  appendMeta(card, '源区间', `${formatMs(item.source_in_ms)} – ${formatMs(item.source_out_ms)}`)
  if (item.anchor_in_ms != null && item.anchor_out_ms != null) {
    appendMeta(card, 'Anchor', `${formatMs(item.anchor_in_ms)} – ${formatMs(item.anchor_out_ms)}`)
  }
  appendMeta(card, '连续性', item.continuity_status)
  appendMeta(card, '画面族', item.visual_family)
  appendMeta(card, '呈现', item.presentation_type)
  appendMeta(card, '向量分', item.vector_score.toFixed(3))

  const hasMediaKey = Object.prototype.hasOwnProperty.call(mediaById, item.media_id)
  const media = hasMediaKey ? mediaById[item.media_id] : null
  const tooShort = selectedClip != null && !candidateFitsClip(item, selectedClip)
  const unavailable = hasMediaKey && media === null
  if (tooShort) appendMeta(card, '状态', '时长不足')
  else if (unavailable) appendMeta(card, '状态', '素材不可用')

  const replaceable = selectedClip != null && !tooShort && media != null && !editBusy
  const replace = el('button', 'finecut-replace', '替换当前镜头')
  replace.type = 'button'
  replace.disabled = !replaceable
  replace.addEventListener('click', () => handlers.replaceCandidate(item))
  card.append(replace)

  card.draggable = replaceable
  if (replaceable) {
    card.addEventListener('dragstart', (event) => {
      event.dataTransfer?.setData('text/plain', item.candidate_id ?? item.requirement_id)
      handlers.startCandidateDrag(item)
    })
    card.addEventListener('dragend', () => handlers.endCandidateDrag())
  }
  return card
}

function candidateSection(
  level: string,
  items: CandidateItem[],
  selectedClip: TimelineClip | null,
  mediaById: Record<string, MediaReference | null>,
  editBusy: boolean,
  handlers: {
    replaceCandidate: (candidate: CandidateItem) => void
    startCandidateDrag: (candidate: CandidateItem) => void
    endCandidateDrag: () => void
  },
): HTMLElement {
  const section = el('section', 'finecut-section')
  section.dataset.candidateSection = level
  section.append(el('h3', undefined, level))
  const matches = items.filter((item) => item.display_level === level)
  if (!matches.length) {
    section.append(el('div', 'finecut-empty', '暂无候选'))
    return section
  }
  matches.forEach((item) => section.append(
    candidateCard(item, selectedClip, mediaById, editBusy, handlers),
  ))
  return section
}

function renderWorkspace(
  root: HTMLElement,
  state: {
    timeline: TimelineDocument | null
    narration: NarrationReference | null
    candidates: CandidateList | null
    mediaById: Record<string, MediaReference | null>
    mediaResolutionBySource: ReadonlyMap<string, MediaReference | null>
    thumbnailFailures: ReadonlySet<string>
    selectedContextId: string | null
    selectedClipId: string | null
    playheadMs: number
    pixelsPerSecond: number
    timelineScrollLeft: number
    previewStatus: PreviewStatus
    previewClipId: string | null
    previewMedia: MediaReference | null
    loading: boolean
    candidateLoading: boolean
    editBusy: boolean
    saving: boolean
    exporting: boolean
    pastCount: number
    futureCount: number
    notice: string | null
    error: string | null
  },
  handlers: {
    selectSegment: (segment: NarrationSegmentReference) => void
    selectClip: (clip: TimelineClip) => void
    seek: (value: number) => void
    zoom: (direction: -1 | 1) => void
    timelineScrolled: (scrollLeft: number) => void
    thumbnailMissing: (key: string) => void
    replaceCandidate: (candidate: CandidateItem) => void
    startCandidateDrag: (candidate: CandidateItem) => void
    endCandidateDrag: () => void
    dropCandidate: (clip: TimelineClip) => void
    trimClip: (edge: 'left' | 'right', deltaMs: number) => void
    splitClip: () => void
    deleteClip: () => void
    updateClipProperties: (properties: ClipPropertyUpdate) => void
    exportJianying: () => void
    undo: () => void
    redo: () => void
    save: () => void
    playPreview: () => void
    pausePreview: () => void
    previewLoadedMetadata: (video: HTMLVideoElement) => void
    previewTimeUpdate: (video: HTMLVideoElement) => void
    previewError: (video: HTMLVideoElement) => void
  },
): void {
  root.replaceChildren()
  root.className = 'finecut-root'
  const style = el('style')
  style.textContent = STYLE
  root.append(style)

  const header = el('div', 'finecut-header')
  header.append(el('h1', 'finecut-title', 'ClipAtlas 剪辑草稿'))
  const actions = el('div', 'finecut-actions')
  const undo = el('button', 'finecut-action', '撤销')
  undo.type = 'button'
  undo.dataset.undoTimeline = 'true'
  undo.disabled = state.pastCount === 0 || state.editBusy || state.saving
  undo.addEventListener('click', handlers.undo)
  const redo = el('button', 'finecut-action', '重做')
  redo.type = 'button'
  redo.dataset.redoTimeline = 'true'
  redo.disabled = state.futureCount === 0 || state.editBusy || state.saving
  redo.addEventListener('click', handlers.redo)
  const save = el('button', 'finecut-action', state.saving ? '保存中…' : '保存')
  save.type = 'button'
  save.dataset.saveTimeline = 'true'
  save.disabled = state.timeline == null || state.editBusy || state.saving
  save.addEventListener('click', handlers.save)
  const exportJianying = el(
    'button',
    'finecut-action',
    state.exporting ? '导出中…' : '保存并导出剪映草稿',
  )
  exportJianying.type = 'button'
  exportJianying.dataset.exportJianying = 'true'
  exportJianying.disabled = state.timeline == null || state.editBusy || state.saving || state.exporting
  exportJianying.addEventListener('click', handlers.exportJianying)
  actions.append(undo, redo, save, exportJianying)
  if (state.notice) actions.append(el('span', 'finecut-notice', state.notice))
  header.append(actions)
  root.append(header)

  if (state.loading) {
    root.append(el('div', 'finecut-status', '正在加载时间线…'))
    return
  }
  if (state.error) {
    root.append(el('div', 'finecut-status finecut-error', state.error))
    return
  }
  if (!state.timeline || !state.narration) {
    root.append(el('div', 'finecut-status', '没有可显示的精剪数据'))
    return
  }

  const selectedClip = findSelectedClip(state.timeline, state.selectedClipId)
  const activePreviewClip = findActiveVideoClip(state.timeline, state.playheadMs)
  const candidateHandlers = {
    replaceCandidate: handlers.replaceCandidate,
    startCandidateDrag: handlers.startCandidateDrag,
    endCandidateDrag: handlers.endCandidateDrag,
  }

  const grid = el('div', 'finecut-grid')
  const candidatesPanel = el('aside', 'finecut-panel finecut-candidates')
  candidatesPanel.append(el('h2', undefined, '智能候选'))

  if (state.candidateLoading) {
    candidatesPanel.append(el('div', 'finecut-empty', '正在读取当前句候选…'))
  } else {
    const visible = (state.candidates?.items ?? []).filter(visibleCandidate)
    NORMAL_LEVELS.forEach((level) => candidatesPanel.append(
      candidateSection(
        level,
        visible,
        selectedClip,
        state.mediaById,
        state.editBusy,
        candidateHandlers,
      ),
    ))

    const fallback = el('details', 'finecut-section finecut-fallback')
    fallback.dataset.candidateSection = 'fallback'
    fallback.append(el('summary', undefined, '兜底素材'))
    const fallbackItems = visible.filter((item) =>
      item.display_level === 'Fallback/Source' || item.display_level === 'Fallback/Reuse',
    )
    if (!fallbackItems.length) fallback.append(el('div', 'finecut-empty', '暂无兜底素材'))
    fallbackItems.forEach((item) => fallback.append(
      candidateCard(item, selectedClip, state.mediaById, state.editBusy, candidateHandlers),
    ))
    candidatesPanel.append(fallback)
  }

  const previewPanel = el('section', 'finecut-panel')
  previewPanel.append(el('h2', undefined, '预览'))
  const preview = el('div', 'finecut-preview')
  const previewPosition = el('div', undefined, `预览位置 ${formatMs(state.playheadMs)}`)
  previewPosition.dataset.previewPosition = 'true'
  preview.append(previewPosition)
  const selectedSegment = state.narration.segments.find((item) => item.id === state.selectedContextId)
  if (selectedSegment) preview.append(el('small', undefined, selectedSegment.text))

  if (
    state.previewStatus === 'ready'
    && state.previewMedia
    && activePreviewClip
    && activePreviewClip.id === state.previewClipId
  ) {
    const video = el('video', 'finecut-preview-video')
    video.dataset.finecutPreviewVideo = 'true'
    video.dataset.previewClipId = activePreviewClip.id
    video.muted = true
    video.defaultMuted = true
    video.preload = 'metadata'
    video.style.opacity = String(activePreviewClip.opacity)
    video.style.transform = previewTransform(activePreviewClip)
    video.setAttribute(
      'src',
      `/api/v1/videos/${encodeURIComponent(state.previewMedia.media_id)}/source-media`,
    )
    video.addEventListener('loadedmetadata', () => handlers.previewLoadedMetadata(video))
    video.addEventListener('timeupdate', () => handlers.previewTimeUpdate(video))
    video.addEventListener('error', () => handlers.previewError(video))
    preview.append(video)

    const controls = el('div', 'finecut-preview-controls')
    const play = el('button', 'finecut-action', '播放')
    play.type = 'button'
    play.setAttribute('aria-label', '播放预览')
    play.addEventListener('click', handlers.playPreview)
    const pause = el('button', 'finecut-action', '暂停')
    pause.type = 'button'
    pause.setAttribute('aria-label', '暂停预览')
    pause.addEventListener('click', handlers.pausePreview)
    controls.append(play, pause)
    preview.append(controls)
  } else if (state.previewStatus === 'resolving') {
    preview.append(el('small', undefined, '正在解析当前 V1 素材…'))
  } else if (state.previewStatus === 'unresolved') {
    preview.append(el('small', undefined, '当前镜头素材无法解析'))
  } else if (state.previewStatus === 'error') {
    preview.append(el('small', undefined, '当前镜头素材无法播放'))
  } else {
    preview.append(el('small', undefined, 'Timeline gap：当前位置没有 V1 clip'))
  }
  preview.append(el('small', undefined, 'V1 画面预览已静音；A1 音频不在本阶段播放'))
  previewPanel.append(preview)

  const seek = el('input', 'finecut-seek')
  seek.type = 'range'
  seek.min = '0'
  seek.max = String(state.timeline.duration_ms)
  seek.step = '100'
  seek.value = String(Math.min(state.playheadMs, state.timeline.duration_ms))
  seek.setAttribute('aria-label', '时间线定位')
  seek.addEventListener('input', () => handlers.seek(Number(seek.value)))
  previewPanel.append(seek)

  const effectsPanel = el('section', 'finecut-panel finecut-effects')
  effectsPanel.append(el('h2', undefined, '效果'))
  if (!selectedClip) {
    const empty = el('div', 'finecut-empty', '请选择一个 V1 镜头调整效果')
    empty.dataset.effectsEmpty = 'true'
    effectsPanel.append(empty)
  } else {
    const positionX = transformValue(selectedClip, 'position_x', 0)
    const positionY = transformValue(selectedClip, 'position_y', 0)
    const scale = transformValue(selectedClip, 'scale', 1)
    const rotation = transformValue(selectedClip, 'rotation', 0)
    const controls = el('div', 'finecut-effects-grid')

    const makeInput = (
      labelText: string,
      ariaLabel: string,
      value: number,
      options: { min?: number; max?: number; step?: number } = {},
    ): HTMLInputElement => {
      const field = el('label', 'finecut-effects-field')
      field.append(el('span', undefined, labelText))
      const input = el('input', 'finecut-effects-input')
      input.type = 'number'
      input.value = String(value)
      if (options.min != null) input.min = String(options.min)
      if (options.max != null) input.max = String(options.max)
      if (options.step != null) input.step = String(options.step)
      input.setAttribute('aria-label', ariaLabel)
      input.disabled = state.editBusy
      field.append(input)
      controls.append(field)
      return input
    }

    const opacityInput = makeInput('Opacity', '效果透明度', selectedClip.opacity, {
      min: 0,
      max: 1,
      step: 0.05,
    })
    const volumeInput = makeInput('Volume', '效果音量', selectedClip.volume, {
      min: 0,
      step: 0.05,
    })
    const positionXInput = makeInput('Position X', '效果位置 X', positionX, { step: 1 })
    const positionYInput = makeInput('Position Y', '效果位置 Y', positionY, { step: 1 })
    const scaleInput = makeInput('Scale', '效果缩放', scale, { min: 0.01, step: 0.05 })
    const rotationInput = makeInput('Rotation', '效果旋转', rotation, { step: 1 })
    effectsPanel.append(controls)

    const effectsActions = el('div', 'finecut-effects-actions')
    const apply = el('button', 'finecut-action', state.editBusy ? '应用中…' : '应用效果')
    apply.type = 'button'
    apply.dataset.applyEffects = 'true'
    apply.disabled = state.editBusy
    apply.addEventListener('click', () => {
      const opacity = Number(opacityInput.value)
      const volume = Number(volumeInput.value)
      const nextPositionX = Number(positionXInput.value)
      const nextPositionY = Number(positionYInput.value)
      const nextScale = Number(scaleInput.value)
      const nextRotation = Number(rotationInput.value)
      if (
        !Number.isFinite(opacity)
        || !Number.isFinite(volume)
        || !Number.isFinite(nextPositionX)
        || !Number.isFinite(nextPositionY)
        || !Number.isFinite(nextScale)
        || !Number.isFinite(nextRotation)
        || opacity < 0
        || opacity > 1
        || volume < 0
        || nextScale <= 0
      ) return

      const update: ClipPropertyUpdate = {}
      if (opacity !== selectedClip.opacity) update.opacity = opacity
      if (volume !== selectedClip.volume) update.volume = volume
      const transform: Record<string, number> = {}
      if (nextPositionX !== positionX) transform.position_x = nextPositionX
      if (nextPositionY !== positionY) transform.position_y = nextPositionY
      if (nextScale !== scale) transform.scale = nextScale
      if (nextRotation !== rotation) transform.rotation = nextRotation
      if (Object.keys(transform).length) update.transform = transform
      if (!Object.keys(update).length) return
      handlers.updateClipProperties(update)
    })
    effectsActions.append(apply)
    effectsPanel.append(effectsActions)
  }

  const timelinePanel = el('section', 'finecut-panel finecut-timeline')
  const timelineHeader = el('div', 'finecut-timeline-toolbar')
  timelineHeader.append(el('h2', undefined, '时间线'))
  const zoomControls = el('div', 'finecut-zoom')
  const zoomOut = el('button', 'finecut-action', '−')
  zoomOut.type = 'button'
  zoomOut.setAttribute('aria-label', '缩小时间线')
  zoomOut.disabled = state.pixelsPerSecond === ZOOM_LEVELS[0]
  zoomOut.addEventListener('click', () => handlers.zoom(-1))
  const zoomValue = el('span', 'finecut-zoom-value', `${state.pixelsPerSecond} px/s`)
  const zoomIn = el('button', 'finecut-action', '+')
  zoomIn.type = 'button'
  zoomIn.setAttribute('aria-label', '放大时间线')
  zoomIn.disabled = state.pixelsPerSecond === ZOOM_LEVELS[ZOOM_LEVELS.length - 1]
  zoomIn.addEventListener('click', () => handlers.zoom(1))
  zoomControls.append(zoomOut, zoomValue, zoomIn)
  timelineHeader.append(zoomControls)
  timelinePanel.append(timelineHeader)

  const timelineLayout = el('div', 'finecut-timeline-layout')
  const labelColumn = el('div', 'finecut-track-labels')
  labelColumn.append(
    el('div', 'finecut-track-label-spacer'),
    el('div', 'finecut-track-label', 'V1 主画面'),
    el('div', 'finecut-track-label', 'T1 旁白文本/字幕上下文'),
    el('div', 'finecut-track-label', 'A1 Narration'),
  )

  const scroll = el('div', 'finecut-timeline-scroll')
  scroll.scrollLeft = state.timelineScrollLeft
  scroll.addEventListener('scroll', () => handlers.timelineScrolled(scroll.scrollLeft))
  scroll.addEventListener('wheel', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.deltaY !== 0) {
      event.preventDefault()
      handlers.timelineScrolled(scroll.scrollLeft)
      handlers.zoom(event.deltaY < 0 ? 1 : -1)
      return
    }
    if (event.shiftKey && event.deltaY !== 0) {
      event.preventDefault()
      scroll.scrollLeft = Math.max(0, scroll.scrollLeft + event.deltaY)
      handlers.timelineScrolled(scroll.scrollLeft)
    }
  })
  const surface = el('div', 'finecut-timeline-surface')
  surface.dataset.timelineSurface = 'true'
  surface.dataset.pixelsPerSecond = String(state.pixelsPerSecond)
  const timelineWidth = timeToPx(state.timeline.duration_ms, state.pixelsPerSecond)
  surface.style.width = `${timelineWidth}px`

  const seekFromClientX = (clientX: number, surfaceLeft: number, snap: boolean) => {
    const pixelOffset = clientX - surfaceLeft
    const raw = clampTimelineMs(
      pixelOffset / state.pixelsPerSecond * 1000,
      state.timeline!.duration_ms,
    )
    handlers.seek(snap
      ? snapTimelineMs(raw, state.timeline!, state.narration!, state.pixelsPerSecond)
      : raw)
  }

  surface.addEventListener('click', (event) => {
    if ((event.target as HTMLElement).closest('[data-timeline-item]')) return
    seekFromClientX(event.clientX, surface.getBoundingClientRect().left, false)
  })

  const ruler = el('div', 'finecut-ruler')
  ruler.dataset.timelineRuler = 'true'
  const durationSeconds = state.timeline.duration_ms / 1000
  const rulerStepSeconds = durationSeconds <= 30 ? 1 : durationSeconds <= 120 ? 5 : 10
  for (let second = 0; second <= durationSeconds; second += rulerStepSeconds) {
    const tick = el('div', 'finecut-ruler-tick', formatMs(second * 1000))
    tick.style.left = `${second * state.pixelsPerSecond}px`
    ruler.append(tick)
  }
  surface.append(ruler)

  const videoTrack = state.timeline.tracks.find((track) => track.kind === 'video')
  const v1 = el('div', 'finecut-track finecut-track-v1')
  v1.dataset.track = 'V1'
  const v1Body = el('div', 'finecut-track-body')
  if (!videoTrack?.clips.length) {
    v1Body.append(el('div', 'finecut-empty', '没有视频片段'))
  } else {
    videoTrack.clips.forEach((clip, index) => {
      const button = el('button', 'finecut-clip')
      button.type = 'button'
      button.dataset.clipId = clip.id
      button.dataset.timelineItem = 'clip'
      button.title = clip.source_path
      button.style.left = `${timeToPx(clip.timeline_start_ms, state.pixelsPerSecond)}px`
      button.style.width = `${timeToPx(clip.duration_ms, state.pixelsPerSecond)}px`

      const mediaKnown = state.mediaResolutionBySource.has(clip.source_id)
      const media = mediaKnown ? (state.mediaResolutionBySource.get(clip.source_id) ?? null) : undefined
      button.dataset.mediaStatus = mediaKnown ? (media ? 'ready' : 'missing') : 'resolving'

      if (media) {
        const thumbnail = clipThumbnail(clip, media)
        if (state.thumbnailFailures.has(thumbnail.key)) {
          button.dataset.thumbnailMissing = 'true'
        } else {
          const image = el('img', 'finecut-clip-thumbnail')
          image.dataset.clipThumbnail = 'true'
          image.alt = ''
          image.loading = 'lazy'
          image.src = thumbnail.url
          image.addEventListener('error', () => {
            handlers.thumbnailMissing(thumbnail.key)
            button.dataset.thumbnailMissing = 'true'
            image.remove()
          })
          button.append(image)
        }
      }

      const content = el('span', 'finecut-clip-content')
      const label = el('span', 'finecut-clip-label', sourceDisplayName(clip, media))
      label.dataset.clipLabel = 'true'
      const source = el(
        'span',
        'finecut-clip-source',
        `${clip.source_id} · ${formatMs(clip.source_in_ms)} – ${formatMs(clip.source_out_ms)} · ${formatMs(clip.duration_ms)} · 镜头 ${index + 1}`,
      )
      source.dataset.clipSource = 'true'
      content.append(label, source)

      const marker = presentationMarker(clip, media, state.narration!, state.candidates)
      if (marker) {
        button.dataset.presentationMarker = marker
        const badge = el('span', 'finecut-clip-marker', markerLabel(marker))
        badge.dataset.clipMarker = marker
        content.append(badge)
      }
      if (mediaKnown && media === null) {
        const missing = el('span', 'finecut-clip-missing', '素材不可解析')
        missing.dataset.clipMissing = 'true'
        content.append(missing)
      }
      button.append(content)

      const selected = clip.id === state.selectedClipId
      if (selected) button.classList.add('finecut-selected')
      button.addEventListener('click', (event) => {
        event.stopPropagation()
        handlers.selectClip(clip)
      })
      button.addEventListener('dragover', (event) => {
        if (clip.id === state.selectedClipId) event.preventDefault()
      })
      button.addEventListener('drop', (event) => {
        event.preventDefault()
        event.stopPropagation()
        handlers.dropCandidate(clip)
      })
      v1Body.append(button)

      if (!selected) return

      const addTrimHandle = (edge: 'left' | 'right', timelineMs: number) => {
        const handle = el('button', 'finecut-trim-handle')
        handle.type = 'button'
        handle.dataset.trimHandle = edge
        handle.dataset.timelineItem = 'trim-handle'
        handle.setAttribute('aria-label', edge === 'left' ? '左裁手柄' : '右裁手柄')
        handle.style.left = `${timeToPx(timelineMs, state.pixelsPerSecond)}px`
        handle.disabled = state.editBusy
        handle.addEventListener('click', (event) => {
          event.preventDefault()
          event.stopPropagation()
        })
        handle.addEventListener('pointerdown', (event) => {
          if (state.editBusy) return
          event.preventDefault()
          event.stopPropagation()
          const startX = event.clientX
          let latestX = startX
          const onPointerMove = (moveEvent: PointerEvent) => {
            latestX = moveEvent.clientX
          }
          const onPointerUp = (upEvent: PointerEvent) => {
            latestX = upEvent.clientX
            window.removeEventListener('pointermove', onPointerMove)
            window.removeEventListener('pointerup', onPointerUp)
            const inwardPixels = edge === 'left' ? latestX - startX : startX - latestX
            if (!(inwardPixels > 0)) return
            const rawDeltaMs = inwardPixels / state.pixelsPerSecond * 1000
            const clipStart = clip.timeline_start_ms
            const clipEnd = clip.timeline_start_ms + clip.duration_ms
            const rawBoundary = edge === 'left'
              ? clipStart + rawDeltaMs
              : clipEnd - rawDeltaMs
            const snappedBoundary = snapTimelineMs(
              rawBoundary,
              state.timeline!,
              state.narration!,
              state.pixelsPerSecond,
            )
            const deltaMs = Math.round(edge === 'left'
              ? snappedBoundary - clipStart
              : clipEnd - snappedBoundary)
            if (deltaMs <= 0) return
            handlers.trimClip(edge, deltaMs)
          }
          window.addEventListener('pointermove', onPointerMove)
          window.addEventListener('pointerup', onPointerUp)
        })
        v1Body.append(handle)
      }

      addTrimHandle('left', clip.timeline_start_ms)
      addTrimHandle('right', clip.timeline_start_ms + clip.duration_ms)

      const visualActions = el('div', 'finecut-visual-actions')
      visualActions.dataset.timelineItem = 'visual-actions'
      visualActions.style.left = `${timeToPx(
        clip.timeline_start_ms + clip.duration_ms,
        state.pixelsPerSecond,
      ) - 6}px`

      const visualSplit = el('button', 'finecut-visual-action', '拆')
      visualSplit.type = 'button'
      visualSplit.dataset.visualSplit = 'true'
      visualSplit.setAttribute('aria-label', '视觉时间线拆分')
      visualSplit.disabled = state.editBusy
        || !(clip.timeline_start_ms < state.playheadMs
          && state.playheadMs < clip.timeline_start_ms + clip.duration_ms)
      visualSplit.addEventListener('click', (event) => {
        event.preventDefault()
        event.stopPropagation()
        handlers.splitClip()
      })

      const visualDelete = el('button', 'finecut-visual-action', '删')
      visualDelete.type = 'button'
      visualDelete.dataset.visualDelete = 'true'
      visualDelete.setAttribute('aria-label', '视觉时间线删除')
      visualDelete.disabled = state.editBusy
      visualDelete.addEventListener('click', (event) => {
        event.preventDefault()
        event.stopPropagation()
        handlers.deleteClip()
      })

      visualActions.append(visualSplit, visualDelete)
      v1Body.append(visualActions)
    })
  }
  v1.append(v1Body)
  surface.append(v1)

  const t1 = el('div', 'finecut-track finecut-track-t1')
  t1.dataset.track = 'T1'
  const t1Body = el('div', 'finecut-track-body')
  state.narration.segments.forEach((segment) => {
    const button = el(
      'button',
      'finecut-segment',
      `${segment.text} · ${formatMs(segment.end_ms - segment.start_ms)}`,
    )
    button.type = 'button'
    button.dataset.contextId = segment.id
    button.dataset.timelineItem = 'segment'
    button.style.left = `${timeToPx(segment.start_ms, state.pixelsPerSecond)}px`
    button.style.width = `${timeToPx(segment.end_ms - segment.start_ms, state.pixelsPerSecond)}px`
    if (segment.id === state.selectedContextId) {
      button.classList.add('finecut-selected')
      button.dataset.selectedContext = segment.id
    }
    button.addEventListener('click', (event) => {
      event.stopPropagation()
      handlers.selectSegment(segment)
    })
    t1Body.append(button)
  })
  t1.append(t1Body)
  surface.append(t1)

  const a1 = el('div', 'finecut-track finecut-track-a1')
  a1.dataset.track = 'A1'
  const a1Body = el('div', 'finecut-track-body')
  const audio = el(
    'div',
    'finecut-audio',
    `旁白修订 ${state.narration.revision} · ${formatMs(state.narration.duration_ms)} · ${state.narration.audio_uri ?? '无独立音频文件'}`,
  )
  audio.dataset.timelineItem = 'audio'
  audio.style.left = '0px'
  audio.style.width = `${timeToPx(state.narration.duration_ms, state.pixelsPerSecond)}px`
  a1Body.append(audio)
  a1.append(a1Body)
  surface.append(a1)

  const playhead = el('div', 'finecut-playhead')
  playhead.dataset.playhead = 'true'
  playhead.dataset.timelineItem = 'playhead'
  playhead.style.left = `${timeToPx(state.playheadMs, state.pixelsPerSecond)}px`
  const playheadHit = el('div', 'finecut-playhead-hit')
  playhead.append(playheadHit)
  playhead.addEventListener('pointerdown', (event) => {
    event.preventDefault()
    event.stopPropagation()
    const surfaceLeft = surface.getBoundingClientRect().left
    const onPointerMove = (moveEvent: PointerEvent) => {
      seekFromClientX(moveEvent.clientX, surfaceLeft, true)
    }
    const onPointerUp = (upEvent: PointerEvent) => {
      seekFromClientX(upEvent.clientX, surfaceLeft, true)
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
    }
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
  })
  surface.append(playhead)

  scroll.append(surface)
  timelineLayout.append(labelColumn, scroll)
  timelinePanel.append(timelineLayout)

  const editControls = el('div', 'finecut-edit-controls')
  editControls.append(el('span', 'finecut-edit-label', '裁剪毫秒'))
  const trimInput = el('input', 'finecut-edit-input')
  trimInput.type = 'number'
  trimInput.min = '1'
  trimInput.step = '100'
  trimInput.value = '100'
  trimInput.setAttribute('aria-label', '裁剪毫秒')
  editControls.append(trimInput)

  const leftTrim = el('button', 'finecut-action', '左裁')
  leftTrim.type = 'button'
  leftTrim.disabled = selectedClip == null || state.editBusy
  leftTrim.addEventListener('click', () => handlers.trimClip('left', Number(trimInput.value)))
  const rightTrim = el('button', 'finecut-action', '右裁')
  rightTrim.type = 'button'
  rightTrim.disabled = selectedClip == null || state.editBusy
  rightTrim.addEventListener('click', () => handlers.trimClip('right', Number(trimInput.value)))

  const split = el('button', 'finecut-action', '在播放头拆分')
  split.type = 'button'
  split.dataset.splitAtPlayhead = 'true'
  const splitAllowed = selectedClip != null
    && selectedClip.timeline_start_ms < state.playheadMs
    && state.playheadMs < selectedClip.timeline_start_ms + selectedClip.duration_ms
  split.disabled = !splitAllowed || state.editBusy
  split.addEventListener('click', handlers.splitClip)

  const remove = el('button', 'finecut-action', '删除镜头')
  remove.type = 'button'
  remove.dataset.deleteSelected = 'true'
  remove.disabled = selectedClip == null || state.editBusy
  remove.addEventListener('click', handlers.deleteClip)
  editControls.append(leftTrim, rightTrim, split, remove)
  timelinePanel.append(editControls)

  grid.append(candidatesPanel, previewPanel, effectsPanel, timelinePanel)
  root.append(grid)
}

export function mountFineCut(root: HTMLElement, options: FineCutMountOptions): () => void {
  let destroyed = false
  let draggedCandidate: CandidateItem | null = null
  let previewRequestSerial = 0
  const mediaResolutionCache = new Map<string, MediaReference | null>()
  const mediaResolutionInFlight = new Map<string, Promise<MediaReference | null>>()
  const thumbnailFailures = new Set<string>()
  const state = {
    timeline: null as TimelineDocument | null,
    narration: null as NarrationReference | null,
    candidates: null as CandidateList | null,
    mediaById: {} as Record<string, MediaReference | null>,
    selectedContextId: null as string | null,
    selectedClipId: null as string | null,
    playheadMs: 0,
    pixelsPerSecond: ZOOM_LEVELS[DEFAULT_ZOOM_INDEX] as number,
    timelineScrollLeft: 0,
    previewStatus: 'gap' as PreviewStatus,
    previewClipId: null as string | null,
    previewSourceId: null as string | null,
    previewMedia: null as MediaReference | null,
    previewResumeOnLoad: false,
    loading: true,
    candidateLoading: false,
    editBusy: false,
    saving: false,
    exporting: false,
    past: [] as TimelineDocument[],
    future: [] as TimelineDocument[],
    notice: null as string | null,
    error: null as string | null,
  }

  const currentPreviewVideo = (): HTMLVideoElement | null =>
    root.querySelector<HTMLVideoElement>('[data-finecut-preview-video]')

  const currentTimelineScroll = (): HTMLElement | null =>
    root.querySelector<HTMLElement>('.finecut-timeline-scroll')

  const resolveMediaForSource = (sourceId: string): Promise<MediaReference | null> => {
    if (mediaResolutionCache.has(sourceId)) {
      return Promise.resolve(mediaResolutionCache.get(sourceId) ?? null)
    }
    const pending = mediaResolutionInFlight.get(sourceId)
    if (pending) return pending
    const request = requestOptionalJson<MediaReference>(
      `/api/v1/finecut/plans/${encodeURIComponent(options.planId)}/media-resolution/${encodeURIComponent(sourceId)}`,
    ).then((media) => {
      mediaResolutionCache.set(sourceId, media)
      return media
    }).finally(() => {
      mediaResolutionInFlight.delete(sourceId)
    })
    mediaResolutionInFlight.set(sourceId, request)
    return request
  }

  const ensureTimelineMsVisible = (valueMs: number) => {
    if (!state.timeline) return
    const scroll = currentTimelineScroll()
    if (!scroll || scroll.clientWidth <= 0) return
    const x = timeToPx(clampTimelineMs(valueMs, state.timeline.duration_ms), state.pixelsPerSecond)
    const margin = Math.min(TIMELINE_SCROLL_MARGIN_PX, Math.max(0, scroll.clientWidth / 3))
    const left = scroll.scrollLeft
    const right = left + scroll.clientWidth
    let next = left
    if (x < left + margin) next = Math.max(0, x - margin)
    else if (x > right - margin) next = Math.max(0, x - scroll.clientWidth + margin)
    if (next === left) return
    scroll.scrollLeft = next
    state.timelineScrollLeft = next
  }

  const syncPlayheadDom = () => {
    if (!state.timeline) return
    const position = root.querySelector<HTMLElement>('[data-preview-position]')
    if (position) position.textContent = `预览位置 ${formatMs(state.playheadMs)}`

    const seek = root.querySelector<HTMLInputElement>('.finecut-seek')
    if (seek) seek.value = String(Math.min(state.playheadMs, state.timeline.duration_ms))

    const playhead = root.querySelector<HTMLElement>('[data-playhead]')
    if (playhead) {
      playhead.style.left = `${timeToPx(state.playheadMs, state.pixelsPerSecond)}px`
    }

    const selectedClip = findSelectedClip(state.timeline, state.selectedClipId)
    const allowed = selectedClip != null
      && selectedClip.timeline_start_ms < state.playheadMs
      && state.playheadMs < selectedClip.timeline_start_ms + selectedClip.duration_ms
    root.querySelectorAll<HTMLButtonElement>('[data-split-at-playhead], [data-visual-split]')
      .forEach((splitButton) => {
        splitButton.disabled = !allowed || state.editBusy
      })
    ensureTimelineMsVisible(state.playheadMs)
  }

  const syncCurrentVideoToPlayhead = () => {
    if (state.previewStatus !== 'ready') return
    const video = currentPreviewVideo()
    const clip = findActiveVideoClip(state.timeline, state.playheadMs)
    if (!video || !clip || clip.id !== state.previewClipId) return
    const target = sourceTimeSeconds(clip, state.playheadMs)
    if (Math.abs(video.currentTime - target) > 0.001) video.currentTime = target
  }

  const render = () => {
    if (destroyed) return
    renderWorkspace(root, {
      timeline: state.timeline,
      narration: state.narration,
      candidates: state.candidates,
      mediaById: state.mediaById,
      mediaResolutionBySource: mediaResolutionCache,
      thumbnailFailures,
      selectedContextId: state.selectedContextId,
      selectedClipId: state.selectedClipId,
      playheadMs: state.playheadMs,
      pixelsPerSecond: state.pixelsPerSecond,
      timelineScrollLeft: state.timelineScrollLeft,
      previewStatus: state.previewStatus,
      previewClipId: state.previewClipId,
      previewMedia: state.previewMedia,
      loading: state.loading,
      candidateLoading: state.candidateLoading,
      editBusy: state.editBusy,
      saving: state.saving,
      exporting: state.exporting,
      pastCount: state.past.length,
      futureCount: state.future.length,
      notice: state.notice,
      error: state.error,
    }, {
      selectSegment: (segment) => {
        state.selectedContextId = segment.id
        state.playheadMs = segment.start_ms
        state.candidates = null
        state.mediaById = {}
        render()
        ensureTimelineMsVisible(state.playheadMs)
        void activatePreviewForCurrentPlayhead(false)
        void loadCandidates(segment.id)
      },
      selectClip: (clip) => {
        state.selectedClipId = clip.id
        state.playheadMs = clip.timeline_start_ms
        const segment = segmentAtClipStart(state.narration, clip)
        if (!segment) {
          state.selectedContextId = null
          state.candidates = null
          state.mediaById = {}
          state.candidateLoading = false
          render()
          ensureTimelineMsVisible(clip.timeline_start_ms)
          void activatePreviewForCurrentPlayhead(false)
          return
        }
        if (state.selectedContextId === segment.id) {
          render()
          ensureTimelineMsVisible(clip.timeline_start_ms)
          void activatePreviewForCurrentPlayhead(false)
          return
        }
        state.selectedContextId = segment.id
        state.candidates = null
        state.mediaById = {}
        render()
        ensureTimelineMsVisible(clip.timeline_start_ms)
        void activatePreviewForCurrentPlayhead(false)
        void loadCandidates(segment.id)
      },
      seek: (value) => {
        seekPlayhead(value)
      },
      zoom: (direction) => {
        const currentIndex = ZOOM_LEVELS.indexOf(
          state.pixelsPerSecond as typeof ZOOM_LEVELS[number],
        )
        const safeIndex = currentIndex >= 0 ? currentIndex : DEFAULT_ZOOM_INDEX
        const nextIndex = Math.min(ZOOM_LEVELS.length - 1, Math.max(0, safeIndex + direction))
        if (nextIndex === safeIndex) return
        const scroll = currentTimelineScroll()
        const oldPixelsPerSecond = state.pixelsPerSecond
        const anchorOffset = scroll && scroll.clientWidth > 0
          ? timeToPx(state.playheadMs, oldPixelsPerSecond) - scroll.scrollLeft
          : null
        if (scroll) state.timelineScrollLeft = scroll.scrollLeft
        const video = currentPreviewVideo()
        state.previewResumeOnLoad = Boolean(video && !video.paused)
        state.pixelsPerSecond = ZOOM_LEVELS[nextIndex]
        if (anchorOffset != null) {
          state.timelineScrollLeft = Math.max(
            0,
            timeToPx(state.playheadMs, state.pixelsPerSecond) - anchorOffset,
          )
        }
        render()
        ensureTimelineMsVisible(state.playheadMs)
      },
      timelineScrolled: (scrollLeft) => {
        state.timelineScrollLeft = Math.max(0, scrollLeft)
      },
      thumbnailMissing: (key) => {
        thumbnailFailures.add(key)
      },
      replaceCandidate: (candidate) => {
        void applyReplacement(candidate)
      },
      startCandidateDrag: (candidate) => {
        draggedCandidate = candidate
      },
      endCandidateDrag: () => {
        draggedCandidate = null
      },
      dropCandidate: (clip) => {
        if (clip.id !== state.selectedClipId || draggedCandidate == null) return
        const candidate = draggedCandidate
        draggedCandidate = null
        void applyReplacement(candidate)
      },
      trimClip: (edge, deltaMs) => {
        if (!Number.isFinite(deltaMs) || deltaMs <= 0) return
        void applyClipEdit('/api/v1/finecut/edit/trim', { edge, delta_ms: deltaMs }, true, '裁剪失败')
      },
      splitClip: () => {
        void applyClipEdit(
          '/api/v1/finecut/edit/split',
          { split_timeline_ms: state.playheadMs },
          true,
          '拆分失败',
        )
      },
      deleteClip: () => {
        void applyClipEdit('/api/v1/finecut/edit/delete', {}, false, '删除失败')
      },
      updateClipProperties: (properties) => {
        void applyClipEdit(
          '/api/v1/finecut/edit/properties',
          properties,
          true,
          '效果更新失败',
        )
      },
      exportJianying: () => {
        void exportJianying()
      },
      undo: () => {
        if (!state.timeline || !state.past.length) return
        const previous = state.past.pop()
        if (!previous) return
        state.future.unshift(state.timeline)
        state.timeline = previous
        state.notice = null
        render()
        const selected = findSelectedClip(state.timeline, state.selectedClipId)
        if (selected) ensureTimelineMsVisible(selected.timeline_start_ms)
        void refreshPresentationMedia()
        void activatePreviewForCurrentPlayhead(false)
      },
      redo: () => {
        if (!state.timeline || !state.future.length) return
        const next = state.future.shift()
        if (!next) return
        state.past.push(state.timeline)
        state.timeline = next
        state.notice = null
        render()
        const selected = findSelectedClip(state.timeline, state.selectedClipId)
        if (selected) ensureTimelineMsVisible(selected.timeline_start_ms)
        void refreshPresentationMedia()
        void activatePreviewForCurrentPlayhead(false)
      },
      save: () => {
        void saveTimeline()
      },
      playPreview: () => {
        const video = currentPreviewVideo()
        if (!video) return
        state.previewResumeOnLoad = false
        void video.play().catch(() => undefined)
      },
      pausePreview: () => {
        state.previewResumeOnLoad = false
        currentPreviewVideo()?.pause()
      },
      previewLoadedMetadata: (video) => {
        if (video !== currentPreviewVideo()) return
        const clip = findActiveVideoClip(state.timeline, state.playheadMs)
        if (!clip || clip.id !== state.previewClipId) return
        video.currentTime = sourceTimeSeconds(clip, state.playheadMs)
        if (state.previewResumeOnLoad) {
          state.previewResumeOnLoad = false
          void video.play().catch(() => undefined)
        }
      },
      previewTimeUpdate: (video) => {
        handlePreviewTimeUpdate(video)
      },
      previewError: (video) => {
        if (video !== currentPreviewVideo()) return
        video.pause()
        state.previewResumeOnLoad = false
        state.previewStatus = 'error'
        render()
      },
    })
  }

  const refreshPresentationMedia = async () => {
    const timeline = state.timeline
    if (!timeline) return
    const videoTrack = timeline.tracks.find((track) => track.kind === 'video')
    const sourceIds = Array.from(new Set(videoTrack?.clips.map((clip) => clip.source_id) ?? []))
    const unresolved = sourceIds.filter((sourceId) =>
      !mediaResolutionCache.has(sourceId) && !mediaResolutionInFlight.has(sourceId),
    )
    if (!unresolved.length) return
    await Promise.all(unresolved.map((sourceId) => resolveMediaForSource(sourceId)))
    if (!destroyed) render()
  }

  const activatePreviewForCurrentPlayhead = async (resume: boolean) => {
    if (!state.timeline) return
    const clip = findActiveVideoClip(state.timeline, state.playheadMs)
    const currentVideo = currentPreviewVideo()

    if (!clip) {
      previewRequestSerial += 1
      currentVideo?.pause()
      state.previewClipId = null
      state.previewSourceId = null
      state.previewMedia = null
      state.previewResumeOnLoad = false
      state.previewStatus = 'gap'
      render()
      return
    }

    if (state.previewClipId === clip.id && state.previewSourceId === clip.source_id) {
      if (state.previewStatus === 'ready') {
        syncCurrentVideoToPlayhead()
        if (resume) {
          const video = currentPreviewVideo()
          if (video) void video.play().catch(() => undefined)
        }
      } else if (state.previewStatus === 'resolving' && resume) {
        state.previewResumeOnLoad = true
      }
      return
    }

    const requestId = ++previewRequestSerial
    currentVideo?.pause()
    state.previewClipId = clip.id
    state.previewSourceId = clip.source_id
    state.previewMedia = null
    state.previewResumeOnLoad = resume
    state.previewStatus = 'resolving'
    render()

    const media = await resolveMediaForSource(clip.source_id)
    if (destroyed || requestId !== previewRequestSerial) return
    const active = findActiveVideoClip(state.timeline, state.playheadMs)
    if (!active || active.id !== clip.id || active.source_id !== clip.source_id) return

    if (!media) {
      state.previewMedia = null
      state.previewResumeOnLoad = false
      state.previewStatus = 'unresolved'
      render()
      return
    }

    state.previewMedia = media
    state.previewStatus = 'ready'
    render()
  }

  const seekPlayhead = (value: number) => {
    if (!state.timeline || !Number.isFinite(value)) return
    const video = currentPreviewVideo()
    const resume = Boolean(video && !video.paused)
    state.playheadMs = clampTimelineMs(value, state.timeline.duration_ms)
    syncPlayheadDom()

    const active = findActiveVideoClip(state.timeline, state.playheadMs)
    if (
      active
      && active.id === state.previewClipId
      && active.source_id === state.previewSourceId
    ) {
      if (state.previewStatus === 'ready') syncCurrentVideoToPlayhead()
      else if (state.previewStatus === 'resolving' && resume) state.previewResumeOnLoad = true
      return
    }

    if (!active && state.previewStatus === 'gap' && state.previewClipId == null) return
    void activatePreviewForCurrentPlayhead(resume)
  }

  const handlePreviewTimeUpdate = (video: HTMLVideoElement) => {
    if (video !== currentPreviewVideo() || state.previewStatus !== 'ready') return
    const clip = findSelectedClip(state.timeline, state.previewClipId)
    if (!clip) return

    let sourceMs = video.currentTime * 1000
    if (sourceMs >= clip.source_out_ms) {
      const resume = !video.paused
      video.pause()
      state.playheadMs = clip.timeline_start_ms + clip.duration_ms
      syncPlayheadDom()
      void activatePreviewForCurrentPlayhead(resume)
      return
    }

    if (sourceMs < clip.source_in_ms) {
      sourceMs = clip.source_in_ms
      video.currentTime = sourceMs / 1000
    }
    state.playheadMs = clampTimelineMs(
      clip.timeline_start_ms + sourceMs - clip.source_in_ms,
      state.timeline?.duration_ms ?? clip.timeline_start_ms + clip.duration_ms,
    )
    syncPlayheadDom()
  }

  const applyReplacement = async (candidate: CandidateItem) => {
    const timeline = state.timeline
    const clip = findSelectedClip(timeline, state.selectedClipId)
    const media = state.mediaById[candidate.media_id]
    if (!timeline || !clip || !media || !candidateFitsClip(candidate, clip) || state.editBusy) return

    state.editBusy = true
    state.notice = null
    render()
    let changed = false
    try {
      const next = await requestJson<TimelineDocument>('/api/v1/finecut/edit/replace', {
        method: 'POST',
        body: JSON.stringify({
          document: timeline,
          target_clip_id: clip.id,
          candidate,
          media,
        }),
      })
      if (destroyed) return
      state.past.push(timeline)
      state.timeline = next
      state.future = []
      state.selectedClipId = clip.id
      mediaResolutionCache.set(candidate.media_id, media)
      changed = true
    } catch {
      if (!destroyed) state.notice = '替换失败'
    } finally {
      if (!destroyed) {
        state.editBusy = false
        render()
        if (changed) {
          const selected = findSelectedClip(state.timeline, state.selectedClipId)
          if (selected) ensureTimelineMsVisible(selected.timeline_start_ms)
          void refreshPresentationMedia()
          void activatePreviewForCurrentPlayhead(false)
        }
      }
    }
  }

  const applyClipEdit = async (
    path: string,
    payload: Record<string, unknown>,
    keepSelection: boolean,
    failureMessage: string,
  ) => {
    const timeline = state.timeline
    const clip = findSelectedClip(timeline, state.selectedClipId)
    if (!timeline || !clip || state.editBusy) return

    state.editBusy = true
    state.notice = null
    render()
    let changed = false
    try {
      const next = await requestJson<TimelineDocument>(path, {
        method: 'POST',
        body: JSON.stringify({
          document: timeline,
          target_clip_id: clip.id,
          ...payload,
        }),
      })
      if (destroyed) return
      state.past.push(timeline)
      state.timeline = next
      state.future = []
      state.selectedClipId = keepSelection && findSelectedClip(next, clip.id) ? clip.id : null
      changed = true
    } catch {
      if (!destroyed) state.notice = failureMessage
    } finally {
      if (!destroyed) {
        state.editBusy = false
        render()
        if (changed) {
          const selected = findSelectedClip(state.timeline, state.selectedClipId)
          if (selected) ensureTimelineMsVisible(selected.timeline_start_ms)
          void refreshPresentationMedia()
          void activatePreviewForCurrentPlayhead(false)
        }
      }
    }
  }

  const exportJianying = async () => {
    if (!state.timeline || state.editBusy || state.saving || state.exporting) return
    state.editBusy = true
    state.exporting = true
    state.notice = null
    render()
    try {
      const saved = await requestJson<TimelineDocument>(
        `/api/v1/finecut/plans/${encodeURIComponent(options.planId)}/timeline`,
        { method: 'PUT', body: JSON.stringify(state.timeline) },
      )
      const artifact = await requestJson<JianyingDraftArtifact>('/api/v1/exports/jianying', {
        method: 'POST',
        body: JSON.stringify({ plan_id: options.planId }),
      })
      if (destroyed) return
      state.timeline = saved
      state.notice = '剪映草稿已导出：' + artifact.output_path
    } catch (error) {
      if (!destroyed) {
        const reason = error instanceof Error ? `：${error.message}` : ''
        state.notice = `剪映草稿导出失败${reason}`
      }
    } finally {
      if (!destroyed) {
        state.editBusy = false
        state.exporting = false
        render()
      }
    }
  }

  const saveTimeline = async () => {
    if (!state.timeline || state.saving || state.editBusy) return
    state.saving = true
    state.notice = null
    render()
    try {
      const saved = await requestJson<TimelineDocument>(
        `/api/v1/finecut/plans/${encodeURIComponent(options.planId)}/timeline`,
        { method: 'PUT', body: JSON.stringify(state.timeline) },
      )
      if (destroyed) return
      state.timeline = saved
      state.notice = '已保存'
    } catch {
      if (!destroyed) state.notice = '保存失败'
    } finally {
      if (!destroyed) {
        state.saving = false
        render()
        void activatePreviewForCurrentPlayhead(false)
      }
    }
  }

  const handleKeyboardShortcut = (event: KeyboardEvent) => {
    if (event.repeat || isTypingTarget(event.target)) return
    const key = event.key.toLowerCase()
    const modifier = event.ctrlKey || event.metaKey

    if (modifier && key === 'z') {
      event.preventDefault()
      root.querySelector<HTMLButtonElement>(
        event.shiftKey ? '[data-redo-timeline]' : '[data-undo-timeline]',
      )?.click()
      return
    }
    if (modifier && key === 'y') {
      event.preventDefault()
      root.querySelector<HTMLButtonElement>('[data-redo-timeline]')?.click()
      return
    }
    if (modifier && key === 's') {
      event.preventDefault()
      root.querySelector<HTMLButtonElement>('[data-save-timeline]')?.click()
      return
    }
    if (modifier || event.altKey) return

    if (event.key === ' ') {
      event.preventDefault()
      const video = currentPreviewVideo()
      if (!video) return
      root.querySelector<HTMLButtonElement>(
        video.paused ? '[aria-label="播放预览"]' : '[aria-label="暂停预览"]',
      )?.click()
      return
    }
    if (key === 's') {
      event.preventDefault()
      root.querySelector<HTMLButtonElement>('[data-split-at-playhead]')?.click()
      return
    }
    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault()
      root.querySelector<HTMLButtonElement>('[data-delete-selected]')?.click()
    }
  }

  const loadCandidates = async (contextId: string) => {
    state.candidateLoading = true
    render()
    try {
      const list = await requestJson<CandidateList>(
        `/api/v1/finecut/plans/${encodeURIComponent(options.planId)}/candidates/${encodeURIComponent(contextId)}`,
      )
      if (destroyed || state.selectedContextId !== contextId) return
      const accepted = list.context_id === contextId ? list : { context_id: contextId, items: [] }
      const mediaIds = Array.from(new Set(
        accepted.items.filter(visibleCandidate).map((item) => item.media_id),
      ))
      const mediaEntries = await Promise.all(mediaIds.map(async (mediaId) => [
        mediaId,
        await requestOptionalJson<MediaReference>(
          `/api/v1/finecut/media/${encodeURIComponent(mediaId)}`,
        ),
      ] as const))
      if (destroyed || state.selectedContextId !== contextId) return
      mediaEntries.forEach(([mediaId, media]) => {
        if (media) mediaResolutionCache.set(mediaId, media)
      })
      state.mediaById = Object.fromEntries(mediaEntries)
      state.candidates = accepted
    } catch (error) {
      if (destroyed || state.selectedContextId !== contextId) return
      state.error = error instanceof Error ? error.message : '候选读取失败'
    } finally {
      if (!destroyed && state.selectedContextId === contextId) {
        state.candidateLoading = false
        render()
      }
    }
  }

  const load = async () => {
    render()
    try {
      const [timeline, narration] = await Promise.all([
        requestJson<TimelineDocument>(
          `/api/v1/finecut/plans/${encodeURIComponent(options.planId)}/timeline`,
        ),
        requestJson<NarrationReference>(
          `/api/v1/finecut/plans/${encodeURIComponent(options.planId)}/narration`,
        ),
      ])
      if (destroyed) return
      state.timeline = timeline
      state.narration = narration
      state.past = []
      state.future = []
      state.loading = false
      const first = narration.segments[0]
      if (first) {
        state.selectedContextId = first.id
        state.playheadMs = first.start_ms
        render()
        ensureTimelineMsVisible(state.playheadMs)
        void refreshPresentationMedia()
        void activatePreviewForCurrentPlayhead(false)
        await loadCandidates(first.id)
      } else {
        render()
        ensureTimelineMsVisible(state.playheadMs)
        void refreshPresentationMedia()
        void activatePreviewForCurrentPlayhead(false)
      }
    } catch (error) {
      if (destroyed) return
      state.loading = false
      state.error = error instanceof Error ? error.message : '智能精剪读取失败'
      render()
    }
  }

  root.addEventListener('keydown', handleKeyboardShortcut)
  void load()

  return () => {
    destroyed = true
    previewRequestSerial += 1
    root.removeEventListener('keydown', handleKeyboardShortcut)
    currentPreviewVideo()?.pause()
    root.replaceChildren()
  }
}
