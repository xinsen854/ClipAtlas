import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from './errors'
import { apiRequest } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiRequest', () => {
  it('returns parsed JSON on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(apiRequest<{ status: string }>('/health')).resolves.toEqual({ status: 'ok' })
  })

  it('returns undefined for 204 responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))

    await expect(apiRequest<void>('/api/v1/example')).resolves.toBeUndefined()
  })

  it('parses ClipAtlas stable error envelope before generic FastAPI detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: 'speech_rate_limited', message: 'upstream rate limited' },
            detail: 'generic detail should not win',
          }),
          { status: 503, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    const promise = apiRequest('/api/v1/narration/tts')

    await expect(promise).rejects.toMatchObject({
      status: 503,
      code: 'speech_rate_limited',
      message: '语音服务请求过于频繁，请稍后再试',
      technicalMessage: 'upstream rate limited',
    })
  })

  it('normalizes FastAPI string detail while preserving technical detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'project not found' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(apiRequest('/api/v1/projects/missing')).rejects.toMatchObject({
      status: 404,
      message: '没有找到请求的内容',
      technicalMessage: 'project not found',
    })
  })

  it('normalizes FastAPI validation detail arrays', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              { type: 'missing', loc: ['body', 'name'], msg: 'Field required', input: {} },
              { type: 'string_too_short', loc: ['body', 'description'], msg: 'Too short', input: '' },
            ],
          }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    const error = await apiRequest('/api/v1/projects', { method: 'POST' }).catch(
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 422,
      message: '输入内容有误，请检查填写项',
    })
    expect((error as ApiError).technicalMessage).toContain('body.name: Field required')
    expect((error as ApiError).technicalMessage).toContain('body.description: Too short')
  })

  it('normalizes network failures without pretending they are HTTP failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(apiRequest('/health')).rejects.toMatchObject({
      status: 0,
      code: 'network_error',
      message: '无法连接 ClipAtlas 服务',
      technicalMessage: 'Failed to fetch',
    })
  })

  it('sets JSON content type for string bodies but never overrides FormData boundaries', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 })),
    )
    vi.stubGlobal('fetch', fetchMock)

    await apiRequest('/api/v1/projects', {
      method: 'POST',
      body: JSON.stringify({ name: '项目 A' }),
    })

    const jsonHeaders = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(jsonHeaders.get('Accept')).toBe('application/json')
    expect(jsonHeaders.get('Content-Type')).toBe('application/json')

    const form = new FormData()
    form.append('file', new Blob(['audio']), 'narration.wav')
    await apiRequest('/api/v1/narration/import', { method: 'POST', body: form })

    const formHeaders = new Headers(fetchMock.mock.calls[1][1]?.headers)
    expect(formHeaders.get('Accept')).toBe('application/json')
    expect(formHeaders.has('Content-Type')).toBe(false)
  })
})
