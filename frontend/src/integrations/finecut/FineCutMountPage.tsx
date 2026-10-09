import { Alert } from 'antd'
import { useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'

import { fineCutUiAvailable, mountFineCut } from '@finecut-ui'

export function FineCutMountPage() {
  const { planId } = useParams<{ planId: string }>()
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!fineCutUiAvailable || !planId || !rootRef.current) return
    return mountFineCut(rootRef.current, { planId })
  }, [planId])

  if (!fineCutUiAvailable) {
    return <Alert type="info" showIcon message="当前构建未包含剪辑草稿模块" />
  }
  if (!planId) {
    return <Alert type="error" showIcon message="缺少剪辑草稿 ID" />
  }
  return <div ref={rootRef} />
}
