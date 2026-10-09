import type { ReactNode } from 'react'
import { Empty } from 'antd'

type EmptyStateProps = {
  description: string
  extra?: ReactNode
}

export function EmptyState({ description, extra }: EmptyStateProps) {
  return <Empty description={description}>{extra}</Empty>
}
