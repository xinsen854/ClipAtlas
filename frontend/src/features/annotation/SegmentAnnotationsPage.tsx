import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Flex,
  Pagination,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import {
  getLibraryItem,
  getVideoSegments,
  type AnnotationCorrectionResponse,
  type SegmentPage,
  type SemanticAnnotation,
  type UpdateAnnotationInput,
} from '../../api/library'
import {
  setSegmentFallbackRole,
  type SegmentFallbackRole,
} from '../../api/segmentRoles'
import { ErrorBlock } from '../../components/ErrorBlock'
import { LoadingBlock } from '../../components/LoadingBlock'
import { PageHeader } from '../../components/PageHeader'
import { AnnotationEditor } from './AnnotationEditor'
import { useAnnotationCorrection } from './useAnnotationCorrection'

const PAGE_SIZE = 50

const fallbackRoleOptions: { value: SegmentFallbackRole; label: string }[] = [
  { value: 'normal', label: '普通素材' },
  { value: 'generic', label: '通用空镜' },
  { value: 'review_placeholder', label: '审片占位' },
  { value: 'never', label: '禁止使用' },
]

type EditingAnnotation = {
  segmentId: string
  annotation: SemanticAnnotation
}

type SegmentPageWithFallbackRole = Omit<SegmentPage, 'items'> & {
  items: Array<SegmentPage['items'][number] & { fallback_role?: SegmentFallbackRole }>
}

export function segmentPageOffset(page: number, pageSize: number): number {
  return Math.max(0, page - 1) * pageSize
}

function filenameFromPath(path: string): string {
  const normalized = path.replaceAll('\\', '/')
  return normalized.split('/').filter(Boolean).at(-1) ?? path
}

function formatTimestamp(ms: number): string {
  const totalSeconds = ms / 1000
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds - minutes * 60
  return `${String(minutes).padStart(2, '0')}:${seconds.toFixed(3).padStart(6, '0')}`
}

function TagGroup({ values }: { values: string[] }) {
  if (!values.length) return <Typography.Text type="secondary">—</Typography.Text>
  return (
    <Space size={[4, 4]} wrap>
      {values.map((value, index) => (
        <Tag key={`${value}-${index}`}>{value}</Tag>
      ))}
    </Space>
  )
}

function originLabel(annotation: SemanticAnnotation): string {
  return annotation.origin === 'human' ? '人工修正' : 'AI 标注'
}

function correctionAlert(response: AnnotationCorrectionResponse) {
  return {
    type: response.embedding_updated ? ('success' as const) : ('warning' as const),
    description: response.embedding_updated ? '素材索引已更新' : '索引更新失败',
  }
}

export function SegmentAnnotationsPage() {
  const { itemId } = useParams<{ itemId: string }>()
  const [searchParams] = useSearchParams()
  const fromStatus = searchParams.get('fromStatus')
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<EditingAnnotation | null>(null)
  const [lastCorrection, setLastCorrection] = useState<AnnotationCorrectionResponse | null>(null)

  const itemQuery = useQuery({
    queryKey: ['library', 'item', itemId],
    queryFn: () => getLibraryItem(itemId as string),
    enabled: Boolean(itemId),
  })
  const videoId = itemQuery.data?.video_id ?? null
  const offset = segmentPageOffset(page, PAGE_SIZE)
  const segmentsQuery = useQuery({
    queryKey: ['video', 'segments', videoId, { limit: PAGE_SIZE, offset }],
    queryFn: () => getVideoSegments(videoId as string, PAGE_SIZE, offset),
    enabled: Boolean(videoId),
  })
  const correction = useAnnotationCorrection(videoId ?? '')
  const fallbackRoleMutation = useMutation({
    mutationFn: ({ segmentId, role }: { segmentId: string; role: SegmentFallbackRole }) =>
      setSegmentFallbackRole(segmentId, role),
    onSuccess: async () => {
      await segmentsQuery.refetch()
    },
  })

  if (!itemId) return <ErrorBlock error={new Error('missing item id')} title="素材地址无效" />
  if (itemQuery.isPending || (videoId && segmentsQuery.isPending)) {
    return <LoadingBlock label="正在读取片段标注…" />
  }
  if (itemQuery.error) return <ErrorBlock error={itemQuery.error} title="素材详情读取失败" />
  if (segmentsQuery.error) return <ErrorBlock error={segmentsQuery.error} title="片段标注读取失败" />

  const item = itemQuery.data
  if (!item) return <ErrorBlock error={new Error('library item missing')} title="素材不存在" />

  async function saveCorrection(segmentId: string, input: UpdateAnnotationInput) {
    const result = await correction.mutateAsync({ segmentId, input })
    setLastCorrection(result)
  }

  async function handleEditorSubmit(input: UpdateAnnotationInput) {
    if (!editing) return
    await saveCorrection(editing.segmentId, input)
    setEditing(null)
  }

  async function toggleLock(segmentId: string, annotation: SemanticAnnotation) {
    await saveCorrection(segmentId, { locked: !annotation.locked })
  }

  const alert = lastCorrection ? correctionAlert(lastCorrection) : null
  const segmentPage = segmentsQuery.data as SegmentPageWithFallbackRole | undefined

  return (
    <Flex vertical gap={20}>
      <PageHeader
        title={`${filenameFromPath(item.source_path)} · 片段标注`}
        description="查看当前有效语义标注。人工修正保存后由后端建立新修订并重新更新语义索引。"
        extra={
          <Link to={`/library/items/${item.id}${fromStatus ? `?fromStatus=${fromStatus}` : ''}`}>
            <Button>返回素材详情</Button>
          </Link>
        }
      />

      <Alert
        showIcon
        type="info"
        message="片段用途"
        description="通用空镜用于 exact / related 不足时的干净中性补画面；审片占位只在合法素材全部耗尽时使用。两者都不会绕过黑底大字、PPT、密集字幕等污染过滤。"
      />

      {alert ? (
        <Alert
          showIcon
          type={alert.type}
          message="已保存人工修正"
          description={alert.description}
          closable
          onClose={() => setLastCorrection(null)}
        />
      ) : null}
      {correction.error ? <ErrorBlock error={correction.error} title="人工修正保存失败" /> : null}
      {fallbackRoleMutation.error ? (
        <ErrorBlock error={fallbackRoleMutation.error} title="片段用途保存失败" />
      ) : null}

      {!videoId ? (
        <Card variant="borderless">
          <Empty description="当前素材尚未生成可用的视频片段记录" />
        </Card>
      ) : (
        <Flex vertical gap={12}>
          {segmentPage?.items.length ? (
            segmentPage.items.map(({ segment, annotation, fallback_role }, index) => (
              <Card
                key={segment.id}
                variant="borderless"
                title={`片段 ${segmentPage.offset + index + 1} · ${formatTimestamp(segment.start_ms)} — ${formatTimestamp(segment.end_ms)}`}
                extra={
                  <Space wrap>
                    <Select<SegmentFallbackRole>
                      aria-label={`片段 ${segmentPage.offset + index + 1} 用途`}
                      value={fallback_role ?? 'normal'}
                      style={{ width: 120 }}
                      options={fallbackRoleOptions}
                      loading={
                        fallbackRoleMutation.isPending
                        && fallbackRoleMutation.variables?.segmentId === segment.id
                      }
                      disabled={
                        fallbackRoleMutation.isPending
                        && fallbackRoleMutation.variables?.segmentId === segment.id
                      }
                      onChange={(role) => {
                        fallbackRoleMutation.mutate({ segmentId: segment.id, role })
                      }}
                    />
                    {annotation ? (
                      <>
                        <Button
                          size="small"
                          onClick={() => setEditing({ segmentId: segment.id, annotation })}
                        >
                          编辑标注
                        </Button>
                        <Button
                          size="small"
                          loading={correction.isPending && correction.variables?.segmentId === segment.id}
                          onClick={() => void toggleLock(segment.id, annotation)}
                        >
                          {annotation.locked ? '解除锁定' : '锁定标注'}
                        </Button>
                      </>
                    ) : null}
                  </Space>
                }
              >
                {annotation ? (
                  <Flex vertical gap={14}>
                    <Typography.Paragraph style={{ marginBottom: 0 }}>
                      {annotation.description}
                    </Typography.Paragraph>
                    <Space size={[6, 6]} wrap>
                      <Tag>{originLabel(annotation)}</Tag>
                      <Tag>{`修订 ${annotation.revision}`}</Tag>
                      <Tag>{annotation.locked ? '已锁定' : '未锁定'}</Tag>
                      {annotation.confidence === null ? null : (
                        <Tag>{`置信度 ${(annotation.confidence * 100).toFixed(0)}%`}</Tag>
                      )}
                    </Space>
                    <Descriptions column={{ xs: 1, md: 2 }} size="small" bordered>
                      <Descriptions.Item label="人物"><TagGroup values={annotation.characters} /></Descriptions.Item>
                      <Descriptions.Item label="动作"><TagGroup values={annotation.actions} /></Descriptions.Item>
                      <Descriptions.Item label="场景"><TagGroup values={annotation.scene} /></Descriptions.Item>
                      <Descriptions.Item label="情绪"><TagGroup values={annotation.emotions} /></Descriptions.Item>
                      <Descriptions.Item label="物体"><TagGroup values={annotation.objects} /></Descriptions.Item>
                      <Descriptions.Item label="画面文字 / OCR"><TagGroup values={annotation.ocr} /></Descriptions.Item>
                      <Descriptions.Item label="镜头类型">{annotation.shot_type ?? '—'}</Descriptions.Item>
                      <Descriptions.Item label="运镜">{annotation.camera_motion ?? '—'}</Descriptions.Item>
                    </Descriptions>
                  </Flex>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无有效标注" />
                )}
              </Card>
            ))
          ) : (
            <Card variant="borderless">
              <Empty description="暂无片段" />
            </Card>
          )}

          {segmentPage && segmentPage.total > PAGE_SIZE ? (
            <Flex justify="center">
              <Pagination
                current={page}
                pageSize={PAGE_SIZE}
                total={segmentPage.total}
                showSizeChanger={false}
                onChange={(nextPage) => setPage(nextPage)}
              />
            </Flex>
          ) : null}
        </Flex>
      )}

      <AnnotationEditor
        open={editing !== null}
        annotation={editing?.annotation ?? null}
        submitting={correction.isPending}
        onCancel={() => setEditing(null)}
        onSubmit={handleEditorSubmit}
      />
    </Flex>
  )
}
