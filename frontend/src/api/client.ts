import { ApiError, chineseErrorMessage } from './errors'
import { apiPath } from './lanConnection'

type ErrorEnvelope = {
  error?: {
    code?: unknown
    message?: unknown
  }
  detail?: unknown
}

function assertRelativePath(path: string): void {
  if (!path.startsWith('/') || path.startsWith('//')) {
    throw new ApiError({
      status: 0,
      code: 'invalid_api_path',
      message: '前端请求地址无效',
      technicalMessage: `Expected same-origin relative path, received: ${path}`,
    })
  }
}

function validationTechnicalMessage(detail: unknown[]): string {
  return detail
    .map((entry) => {
      if (!entry || typeof entry !== 'object') return String(entry)
      const item = entry as Record<string, unknown>
      const loc = Array.isArray(item.loc) ? item.loc.map(String).join('.') : 'request'
      const msg = typeof item.msg === 'string' ? item.msg : JSON.stringify(item)
      return `${loc}: ${msg}`
    })
    .join('\n')
}

function parseErrorBody(status: number, rawBody: string): ApiError {
  let parsed: ErrorEnvelope | undefined
  if (rawBody) {
    try {
      parsed = JSON.parse(rawBody) as ErrorEnvelope
    } catch {
      return new ApiError({
        status,
        technicalMessage: rawBody,
      })
    }
  }

  const code =
    parsed?.error && typeof parsed.error.code === 'string' ? parsed.error.code : undefined
  const stableMessage =
    parsed?.error && typeof parsed.error.message === 'string'
      ? parsed.error.message
      : undefined

  if (code || stableMessage) {
    return new ApiError({
      status,
      code,
      message: chineseErrorMessage(status, code),
      technicalMessage: stableMessage,
    })
  }

  if (Array.isArray(parsed?.detail)) {
    return new ApiError({
      status,
      message: chineseErrorMessage(status),
      technicalMessage: validationTechnicalMessage(parsed.detail),
    })
  }

  if (typeof parsed?.detail === 'string') {
    return new ApiError({
      status,
      message: chineseErrorMessage(status),
      technicalMessage: parsed.detail,
    })
  }

  return new ApiError({
    status,
    message: chineseErrorMessage(status),
    technicalMessage: rawBody || undefined,
  })
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  assertRelativePath(path)

  const headers = new Headers(init.headers)
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }
  if (typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(apiPath(path), { ...init, headers })
  } catch (caught) {
    const technicalMessage = caught instanceof Error ? caught.message : String(caught)
    throw new ApiError({
      status: 0,
      code: 'network_error',
      message: chineseErrorMessage(0),
      technicalMessage,
    })
  }

  if (response.status === 204) {
    return undefined as T
  }

  const rawBody = await response.text()
  if (!response.ok) {
    throw parseErrorBody(response.status, rawBody)
  }

  if (!rawBody) {
    return undefined as T
  }

  const contentType = response.headers.get('Content-Type') ?? ''
  if (contentType.includes('application/json')) {
    return JSON.parse(rawBody) as T
  }

  try {
    return JSON.parse(rawBody) as T
  } catch {
    return rawBody as T
  }
}
