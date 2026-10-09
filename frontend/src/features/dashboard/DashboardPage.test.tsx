import { describe, expect, it } from 'vitest'

import { resolveNextStep } from './DashboardPage'

const baseState = {
  hasProject: true,
  hasActiveRules: true,
  libraryRootCount: 1,
  libraryItemCount: 10,
  libraryNeedsAttention: false,
  hasActiveNarration: true,
  activePlanId: 'plan-1',
}

describe('dashboard next step priority', () => {
  it('sets project rules before adding materials', () => {
    expect(resolveNextStep({ ...baseState, hasActiveRules: false, libraryRootCount: 0 }))
      .toEqual({ label: '设置本批规则', path: '/rules' })
  })
  it('asks for a project first', () => {
    expect(resolveNextStep({ ...baseState, hasProject: false })).toEqual({
      label: '创建项目',
      path: null,
    })
  })

  it('asks for material when no roots or items exist', () => {
    expect(resolveNextStep({ ...baseState, libraryRootCount: 0 })).toEqual({
      label: '添加素材',
      path: '/library',
    })
    expect(resolveNextStep({ ...baseState, libraryItemCount: 0 })).toEqual({
      label: '添加素材',
      path: '/library',
    })
  })

  it('prioritizes material processing problems before narration', () => {
    expect(
      resolveNextStep({
        ...baseState,
        libraryNeedsAttention: true,
        hasActiveNarration: false,
        activePlanId: null,
      }),
    ).toEqual({ label: '查看素材处理', path: '/library' })
  })

  it('asks for narration when material is ready', () => {
    expect(resolveNextStep({ ...baseState, hasActiveNarration: false, activePlanId: null })).toEqual({
      label: '准备文案与旁白',
      path: '/narration',
    })
  })

  it('asks to generate a rough cut after narration', () => {
    expect(resolveNextStep({ ...baseState, activePlanId: null })).toEqual({
      label: '生成剪辑草稿',
      path: '/rough-cut',
    })
  })

  it('opens the active rough cut when one exists', () => {
    expect(resolveNextStep(baseState)).toEqual({
      label: '继续编辑草稿',
      path: '/rough-cut/plan-1',
    })
  })
})
