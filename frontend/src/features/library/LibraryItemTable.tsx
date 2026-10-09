import { Button, Space, Table, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'

import type { LibraryItem } from '../../api/library'
import { libraryStatusLabels, type LibraryItemStatus } from '../../utils/statusMaps'

const { Text } = Typography

function filenameFromPath(path: string): string {
  const normalized = path.replaceAll('\\', '/')
  return normalized.split('/').filter(Boolean).at(-1) ?? path
}

type LibraryItemTableProps = {
  items: LibraryItem[]
  status?: LibraryItemStatus
  loading?: boolean
  parsingAvailable: boolean
  parsingItemId?: string | null
  reparsingItemId?: string | null
  retryingItemId?: string | null
  onParse: (itemId: string) => void
  onReparse: (itemId: string) => void
  onRetry: (itemId: string) => void
}

export function LibraryItemTable({
  items,
  status,
  loading = false,
  parsingAvailable,
  parsingItemId = null,
  reparsingItemId = null,
  retryingItemId = null,
  onParse,
  onReparse,
  onRetry,
}: LibraryItemTableProps) {
  const detailLink = (itemId: string) =>
    `/library/items/${encodeURIComponent(itemId)}${status ? `?fromStatus=${status}` : ''}`

  return (
    <Table<LibraryItem>
      rowKey="id"
      loading={loading}
      dataSource={items}
      pagination={false}
      columns={[
        {
          title: '素材',
          key: 'source_path',
          render: (_, item) => (
            <Space direction="vertical" size={0}>
              <Link to={detailLink(item.id)}>
                {filenameFromPath(item.source_path)}
              </Link>
              <Text type="secondary" copyable={{ text: item.source_path }}>
                {item.source_path}
              </Text>
            </Space>
          ),
        },
        {
          title: '解析状态',
          dataIndex: 'status',
          key: 'status',
          width: 140,
          render: (status: LibraryItem['status']) => (
            <Tag>{libraryStatusLabels[status]}</Tag>
          ),
        },
        {
          title: '尝试次数',
          dataIndex: 'attempts',
          key: 'attempts',
          width: 100,
        },
        {
          title: '操作',
          key: 'actions',
          width: 120,
          render: (_, item) => {
            if (item.status === 'QUEUED') {
              return (
                <Button
                  size="small"
                  aria-label="单条解析"
                  disabled={!parsingAvailable}
                  loading={parsingItemId === item.id}
                  onClick={() => onParse(item.id)}
                >
                  单条解析
                </Button>
              )
            }
            if (item.status === 'FAILED') {
              return <Button size="small" aria-label="重试" disabled={!parsingAvailable}
                title="重新排队，保留成功片段；后台暂停时请点击继续未完成"
                loading={retryingItemId === item.id} onClick={() => onRetry(item.id)}>
                重试
              </Button>
            }
            if (item.status === 'COMPLETED') {
              return (
                <Button
                  size="small"
                  aria-label="重新解析"
                  disabled={!parsingAvailable}
                  loading={reparsingItemId === item.id}
                  onClick={() => onReparse(item.id)}
                >
                  重新解析
                </Button>
              )
            }
            return null
          },
        },
      ]}
    />
  )
}
