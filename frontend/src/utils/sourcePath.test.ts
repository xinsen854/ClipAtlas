import { describe, expect, it } from 'vitest'
import { readableSourcePath } from './sourcePath'

describe('readableSourcePath', () => {
  it('decodes file URLs and shows a normal Windows path', () => {
    expect(readableSourcePath('file:///D:/BaiduNetdiskDownload/%E6%B3%B0%E9%92%9C700.mp4'))
      .toBe('D:\\BaiduNetdiskDownload\\泰钜700.mp4')
  })
})
