import { describe, expect, it } from 'vitest'

import { formatDuration, formatTimeRange } from './format'

describe('formatDuration', () => {
  it('formats integer milliseconds without losing millisecond precision', () => {
    expect(formatDuration(222_680)).toBe('03:42.680')
    expect(formatDuration(5_000)).toBe('00:05.000')
    expect(formatDuration(3_725_006)).toBe('1:02:05.006')
  })

  it('formats source ranges using the same canonical millisecond clock', () => {
    expect(formatTimeRange(1_250, 4_750)).toBe('00:01.250 – 00:04.750')
  })
})
