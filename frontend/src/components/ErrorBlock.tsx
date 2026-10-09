import { Alert } from 'antd'

import { ApiError } from '../api/errors'

type ErrorBlockProps = {
  error: unknown
  title?: string
}

export function ErrorBlock({ error, title = '操作失败' }: ErrorBlockProps) {
  const apiError = error instanceof ApiError ? error : null
  const message = apiError?.message ?? '发生未知错误'
  const technical = apiError?.technicalMessage

  return (
    <Alert
      type="error"
      showIcon
      message={title}
      description={
        <div>
          <div>{message}</div>
          {technical ? (
            <details style={{ marginTop: 8 }}>
              <summary>技术详情</summary>
              <pre style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{technical}</pre>
            </details>
          ) : null}
        </div>
      }
    />
  )
}
