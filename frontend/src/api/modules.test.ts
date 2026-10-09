import { afterEach, describe, expect, it, vi } from 'vitest'

import { parseLibraryItem, reparseLibraryItem } from './library'
import { searchSegments, searchVideoChunks } from './search'
import { detectBailianModels, testSettingsConnection } from './settings'
import { openExportFolder, openJianying } from './system'

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('typed api modules', () => {
  it('serializes video scope as repeated FastAPI query parameters', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse([])))
    vi.stubGlobal('fetch', fetchMock)

    await searchSegments({ q: '雨夜街头', limit: 12, videoIds: ['video-a', 'video-b'] })

    const path = String(fetchMock.mock.calls[0][0])
    const url = new URL(path, 'http://clipatlas.local')
    expect(url.pathname).toBe('/api/v1/search/segments')
    expect(url.searchParams.get('q')).toBe('雨夜街头')
    expect(url.searchParams.get('limit')).toBe('12')
    expect(url.searchParams.getAll('video_ids')).toEqual(['video-a', 'video-b'])
  })

  it('defaults video chunk search to the 5s profile and can request 30s explicitly', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse([])))
    vi.stubGlobal('fetch', fetchMock)

    await searchVideoChunks({ q: '夜间山路', limit: 20 })
    await searchVideoChunks({ q: '越野篇', granularity: '30s', videoIds: ['video-a'] })

    const defaultUrl = new URL(String(fetchMock.mock.calls[0][0]), 'http://clipatlas.local')
    expect(defaultUrl.pathname).toBe('/api/v1/search/video-chunks')
    expect(defaultUrl.searchParams.get('q')).toBe('夜间山路')
    expect(defaultUrl.searchParams.get('limit')).toBe('20')
    expect(defaultUrl.searchParams.get('granularity')).toBe('5s')

    const coarseUrl = new URL(String(fetchMock.mock.calls[1][0]), 'http://clipatlas.local')
    expect(coarseUrl.searchParams.get('granularity')).toBe('30s')
    expect(coarseUrl.searchParams.getAll('video_ids')).toEqual(['video-a'])
  })

  it('starts one explicit library parse only through the local ClipAtlas endpoint', async () => {
    const item = {
      id: 'item-1',
      root_id: 'root-1',
      source_path: 'D:/素材/movie.mp4',
      size_bytes: 100,
      mtime_ns: 1,
      fingerprint: 'fp',
      processed_fingerprint: 'fp',
      status: 'COMPLETED',
      video_id: 'video-1',
      attempts: 1,
      last_error: null,
      created_at: '2026-09-04T00:00:00Z',
      updated_at: '2026-09-04T00:00:00Z',
    }
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(item)))
    vi.stubGlobal('fetch', fetchMock)

    await expect(parseLibraryItem('item/1')).resolves.toEqual(item)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/library/items/item%2F1/parse')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
  })

  it('starts one explicit library reparse only through the local ClipAtlas endpoint', async () => {
    const item = {
      id: 'item-2',
      root_id: 'root-1',
      source_path: 'D:/素材/movie.mp4',
      size_bytes: 100,
      mtime_ns: 1,
      fingerprint: 'fp',
      processed_fingerprint: 'fp',
      status: 'COMPLETED',
      video_id: 'video-1',
      attempts: 2,
      last_error: null,
      created_at: '2026-09-04T00:00:00Z',
      updated_at: '2026-09-04T00:00:00Z',
    }
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(item)))
    vi.stubGlobal('fetch', fetchMock)

    await expect(reparseLibraryItem('item/2')).resolves.toEqual(item)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/library/items/item%2F2/reparse')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
  })

  it('tests service connectivity only through the local ClipAtlas settings endpoint', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(jsonResponse({ ok: true, code: 'ok', message: '连接成功。' })),
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      testSettingsConnection({
        service: 'video',
        provider: 'qwen',
        api_key: 'typed-secret',
        base_url: 'https://provider.example/v1',
        model: 'model-a',
      }),
    ).resolves.toEqual({ ok: true, code: 'ok', message: '连接成功。' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/settings/test-connection')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({
      service: 'video',
      provider: 'qwen',
      api_key: 'typed-secret',
      base_url: 'https://provider.example/v1',
      model: 'model-a',
    })
  })

  it('checks the locked Bailian models only through the local ClipAtlas endpoint', async () => {
    const response = {
      ok: true,
      code: 'ok',
      message: '模型检测完成。',
      models: {
        'qwen3-vl-embedding': 'available',
        'qwen3.8-flash': 'available',
        'qwen3.5-ocr': 'unavailable',
        'qwen-audio-3.0-asr-flash': 'unavailable',
      },
    }
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(response)))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      detectBailianModels({
        api_key: 'typed-secret',
        base_url: 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
      }),
    ).resolves.toEqual(response)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/settings/bailian/models')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({
      api_key: 'typed-secret',
      base_url: 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
    })
  })

  it('opens an export folder using only the trusted plan id', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ action: 'opened_export_folder', path: '/trusted/export' })),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(openExportFolder('plan-123')).resolves.toEqual({ status: 'opened' })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/system/open-export-folder')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({ plan_id: 'plan-123' })
  })

  it('launches Jianying without accepting a client supplied executable path', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ action: 'launched_jianying', path: 'C:/Jianying/JianyingPro.exe' })),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(openJianying()).resolves.toEqual({ status: 'launched' })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/system/open-jianying')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.body).toBeUndefined()
  })
})