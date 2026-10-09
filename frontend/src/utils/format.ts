function pad(value: number, width = 2): string {
  return String(value).padStart(width, '0')
}

export function formatDuration(durationMs: number): string {
  const safeMs = Math.max(0, Math.trunc(durationMs))
  const hours = Math.floor(safeMs / 3_600_000)
  const minutes = Math.floor((safeMs % 3_600_000) / 60_000)
  const seconds = Math.floor((safeMs % 60_000) / 1_000)
  const milliseconds = safeMs % 1_000

  if (hours > 0) {
    return `${hours}:${pad(minutes)}:${pad(seconds)}.${pad(milliseconds, 3)}`
  }
  return `${pad(minutes)}:${pad(seconds)}.${pad(milliseconds, 3)}`
}

export function formatTimeRange(startMs: number, endMs: number): string {
  return `${formatDuration(startMs)} – ${formatDuration(endMs)}`
}
