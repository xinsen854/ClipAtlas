import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Descriptions, Flex, Progress, Select, Space, Tag, Typography, message } from 'antd'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import {
  getLibraryItem,
  getVideo,
  getVideoIndexProgress,
  updateVideoFallbackRole,
  type IndexSourceProgress,
} from '../../api/library'
import { ErrorBlock } from '../../components/ErrorBlock'
import { LoadingBlock } from '../../components/LoadingBlock'
import { PageHeader } from '../../components/PageHeader'
import { formatDuration } from '../../utils/format'
import { isLibraryItemPending, libraryStatusLabels } from '../../utils/statusMaps'

const stageLabels = {
  visual: 'Visual 视频索引', asr: 'ASR 语音识别', ocr: 'OCR 文字识别', finalizing: '正在完成解析',
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function filenameFromPath(path: string): string {
  const normalized = path.replaceAll('\\', '/')
  return normalized.split('/').filter(Boolean).at(-1) ?? path
}

function IndexProgressRow({
  label,
  progress,
  notApplicableLabel = '不适用',
}: {
  label: string
  progress: IndexSourceProgress
  notApplicableLabel?: string
}) {
  if (!progress.enabled) {
    return (
      <Flex justify="space-between">
        <Typography.Text>{label}</Typography.Text>
        <Tag>未启用</Tag>
      </Flex>
    )
  }
  if (!progress.applicable) {
    return (
      <Flex justify="space-between">
        <Typography.Text>{label}</Typography.Text>
        <Tag>{notApplicableLabel}</Tag>
      </Flex>
    )
  }
  const percent =
    progress.total > 0 ? Math.min(100, Math.round((progress.completed / progress.total) * 100)) : 0
  return (
    <Flex vertical gap={4}>
      <Flex justify="space-between" gap={12} wrap>
        <Typography.Text>{label}</Typography.Text>
        <Space size={4} wrap>
          <Typography.Text type="secondary">
            {progress.completed} / {progress.total}
          </Typography.Text>
          {progress.processing > 0 ? <Tag>{`处理中 ${progress.processing}`}</Tag> : null}
          {progress.failed > 0 ? <Tag color="error">{`失败 ${progress.failed}`}</Tag> : null}
        </Space>
      </Flex>
      <Progress percent={percent} showInfo={false} size="small" />
    </Flex>
  )
}

export function LibraryItemPage() {
  const queryClient = useQueryClient()
  const { itemId } = useParams<{ itemId: string }>()
  const [searchParams] = useSearchParams()
  const fromStatus = searchParams.get('fromStatus')
  const itemQuery = useQuery({
    queryKey: ['library', 'item', itemId],
    queryFn: () => getLibraryItem(itemId as string),
    enabled: Boolean(itemId),
    refetchInterval: (query) => isLibraryItemPending(query.state.data?.status) ? 5000 : false,
  })
  const videoId = itemQuery.data?.prepared_video_id ?? itemQuery.data?.video_id ?? null
  const videoQuery = useQuery({
    queryKey: ['video', videoId],
    queryFn: () => getVideo(videoId as string),
    enabled: Boolean(videoId),
  })
  const progressQuery = useQuery({
    queryKey: ['video', videoId, 'index-progress'],
    queryFn: () => getVideoIndexProgress(videoId as string),
    enabled: Boolean(videoId) && !itemQuery.data?.index_progress,
    refetchInterval: isLibraryItemPending(itemQuery.data?.status) ? 5000 : false,
  })
  const fallbackRoleMutation = useMutation({
    mutationFn: (role: 'normal' | 'generic' | 'never') =>
      updateVideoFallbackRole(videoId as string, role),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['video', videoId] })
      void message.success('素材兜底角色已更新')
    },
  })

  if (!itemId) return <ErrorBlock error={new Error('missing item id')} title="素材地址无效" />
  if (itemQuery.isPending || (videoId && videoQuery.isPending)) {
    return <LoadingBlock label="正在读取素材详情…" />
  }
  if (itemQuery.error) return <ErrorBlock error={itemQuery.error} title="素材详情读取失败" />
  if (videoQuery.error) return <ErrorBlock error={videoQuery.error} title="视频元数据读取失败" />

  const item = itemQuery.data
  if (!item) return <ErrorBlock error={new Error('library item missing')} title="素材不存在" />
  const detail = videoQuery.data
  const indexProgress = item.index_progress ?? progressQuery.data

  return (
    <Flex vertical gap={20}>
      <PageHeader
        title={filenameFromPath(item.source_path)}
        description="查看素材处理状态、Visual / ASR / OCR 索引和解析结果。"
        extra={
          <Link to={`/library${fromStatus ? `?status=${fromStatus}` : ''}`}>
            <Button>返回素材库</Button>
          </Link>
        }
      />

      <Card title="素材信息" variant="borderless">
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="完整路径">
            <Typography.Text copyable={{ text: item.source_path }}>{item.source_path}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="处理状态">
            {item.processing_stages?.length ? (
              <Space wrap>{item.processing_stages.map((stage) => (
                <Tag key={stage}>{stageLabels[stage]}</Tag>
              ))}</Space>
            ) : (
              <Tag>{item.processing_stage ? stageLabels[item.processing_stage] : libraryStatusLabels[item.status]}</Tag>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="文件大小">{formatBytes(item.size_bytes)}</Descriptions.Item>
          <Descriptions.Item label="处理尝试次数">{item.attempts}</Descriptions.Item>
          {item.last_error ? (
            <Descriptions.Item label="最近错误">
              <Typography.Text type="danger">{item.last_error}</Typography.Text>
            </Descriptions.Item>
          ) : null}
        </Descriptions>
      </Card>

      <Card title="视频与语义处理" variant="borderless">
        {detail ? (
          <Flex vertical gap={16}>
            <Descriptions column={{ xs: 1, md: 2 }} bordered size="small">
              <Descriptions.Item label="视频时长">
                {detail.video.duration_ms === null ? '未知' : formatDuration(detail.video.duration_ms)}
              </Descriptions.Item>
              <Descriptions.Item label="分辨率">
                {detail.video.width && detail.video.height
                  ? `${detail.video.width} × ${detail.video.height}`
                  : '未知'}
              </Descriptions.Item>
              <Descriptions.Item label="帧率">
                {detail.video.fps === null ? '未知' : `${detail.video.fps.toFixed(3)} fps`}
              </Descriptions.Item>
              <Descriptions.Item label="片段总数">{detail.segment_count}</Descriptions.Item>
              <Descriptions.Item label="粗剪兜底角色">
                <Select
                  aria-label="粗剪兜底角色"
                  value={detail.video.fallback_role ?? 'normal'}
                  loading={fallbackRoleMutation.isPending}
                  style={{ minWidth: 220 }}
                  options={[
                    { value: 'normal', label: '普通素材' },
                    { value: 'generic', label: '通用兜底素材' },
                    { value: 'never', label: '禁止用于粗剪' },
                  ]}
                  onChange={(role) => fallbackRoleMutation.mutate(role)}
                />
              </Descriptions.Item>
              <Descriptions.Item label="已有有效标注">
                {detail.annotation_stats.annotated}
              </Descriptions.Item>
              <Descriptions.Item label="AI 有效标注">
                {detail.annotation_stats.ai_effective}
              </Descriptions.Item>
              <Descriptions.Item label="人工有效标注">
                {detail.annotation_stats.human_effective}
              </Descriptions.Item>
              <Descriptions.Item label="已锁定人工标注">
                {detail.annotation_stats.locked}
              </Descriptions.Item>
            </Descriptions>

            {progressQuery.error ? (
              <ErrorBlock error={progressQuery.error} title="索引进度读取失败" />
            ) : null}
            {indexProgress ? (
              <Card size="small" title="索引进度">
                <Flex vertical gap={12}>
                  <IndexProgressRow label="Visual · 视频向量 · 5 秒" progress={indexProgress.visual} />
                  <IndexProgressRow
                    label="ASR"
                    progress={indexProgress.asr}
                    notApplicableLabel="无音轨"
                  />
                  <IndexProgressRow label="OCR" progress={indexProgress.ocr} />
                  {item.progress_updated_at ? <Typography.Text type="secondary">
                    最近进度更新：{new Date(item.progress_updated_at).toLocaleString()}
                  </Typography.Text> : null}
                  {isLibraryItemPending(item.status) ? <Typography.Text type="secondary">
                    正在解析，每5秒刷新进度；已完成的部分可立即查看。
                  </Typography.Text> : null}
                  <Link to={`/library/items/${item.id}/index-results${fromStatus ? `?fromStatus=${fromStatus}` : ''}`}>
                    <Button type="primary">查看解析结果</Button>
                  </Link>
                </Flex>
              </Card>
            ) : null}

            <Space>
              <Link to={`/library/items/${item.id}/segments${fromStatus ? `?fromStatus=${fromStatus}` : ''}`}>
                <Button>查看片段标注</Button>
              </Link>
            </Space>
          </Flex>
        ) : (
          <Typography.Text type="secondary">
            当前素材尚未生成可用的视频目录记录。处理完成后这里会显示片段和标注统计。
          </Typography.Text>
        )}
      </Card>
    </Flex>
  )
}
