import { describe, expect, it } from 'vitest'

import { toLibraryRootInput } from './LibraryRootDialog'

describe('toLibraryRootInput', () => {
  it('preserves the exact local path and recursive flag', () => {
    expect(
      toLibraryRootInput({
        path: 'E:/视频素材/原样 路径',
        recursive: false,
      }),
    ).toEqual({
      path: 'E:/视频素材/原样 路径',
      recursive: false,
    })
  })
})
