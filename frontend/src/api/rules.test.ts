import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  activateProjectRulePack,
  analyzeProjectRules,
  getActiveProjectRulePack,
  listProjectRulePacks,
  previewProjectRules,
  saveProjectRuleDraft,
} from './rules'

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('project rules api', () => {
  it('analyzes and previews rules through project-scoped endpoints', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ rules: [] })))
    vi.stubGlobal('fetch', fetchMock)

    await analyzeProjectRules('project/1', 'batch instructions')
    await previewProjectRules('project/1', {
      text: 'Model 700 enters public view.',
      rules: [
        {
          kind: 'entity_alias',
          match: 'Model 700',
          replacement: 'flagship domestic off-road SUV',
          enabled: true,
        },
      ],
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/projects/project%2F1/rules/analyze')
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      text: 'batch instructions',
    })

    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/projects/project%2F1/rules/preview')
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({
      text: 'Model 700 enters public view.',
      rules: [
        {
          kind: 'entity_alias',
          match: 'Model 700',
          replacement: 'flagship domestic off-road SUV',
          enabled: true,
        },
      ],
    })
  })

  it('saves, lists, reads active, and activates rule revisions without alternate endpoints', async () => {
    const pack = {
      project_id: 'project-1',
      revision: 2,
      status: 'draft',
      rules: [],
    }
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(pack)))
    vi.stubGlobal('fetch', fetchMock)

    await saveProjectRuleDraft('project-1', [])
    await listProjectRulePacks('project-1')
    await getActiveProjectRulePack('project-1')
    await activateProjectRulePack('project-1', 2)

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/projects/project-1/rules/drafts')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ rules: [] })

    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/projects/project-1/rules')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/v1/projects/project-1/rules/active')
    expect(fetchMock.mock.calls[3][0]).toBe('/api/v1/projects/project-1/rules/2/activate')
    expect((fetchMock.mock.calls[3][1] as RequestInit).method).toBe('POST')
  })
})
