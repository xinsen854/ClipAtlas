import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Alert, Button, Card, Flex, Select, Space, Statistic, Tag, Typography } from 'antd'

import {
  getLibraryItems,
  getLibraryProcessingState,
  getLibrarySummary,
  listLibraryRoots,
  type LibrarySummary,
} from '../../api/library'
import { ErrorBlock } from '../../components/ErrorBlock'
import { LoadingBlock } from '../../components/LoadingBlock'
import { PageHeader } from '../../components/PageHeader'
import { libraryStatusLabels, type LibraryItemStatus } from '../../utils/statusMaps'
import { LibraryItemTable } from './LibraryItemTable'
import { LibraryRootDialog } from './LibraryRootDialog'
import { useLibraryActions } from './useLibraryActions'
import { LibraryMaintenanceActions } from './LibraryMaintenanceActions'
import { useAppStore } from '../../stores/useAppStore'

const PROCESSING_STATUSES: LibraryItemStatus[] = [
  'QUEUED',
  'PROBING',
  'SCENE_DETECTION',
  'FRAME_EXTRACTION',
]

export function shouldPollLibrary(
  summary: LibrarySummary | undefined,
  pageVisible: boolean,
  processingActive: boolean,
): boolean {
  if (!summary || !pageVisible || !processingActive) return false
  return PROCESSING_STATUSES.some((status) => summary[status] > 0)
}

function usePageVisible(): boolean {
  const [visible, setVisible] = useState(() =>
    typeof document === 'undefined' ? true : document.visibilityState !== 'hidden',
  )

  useEffect(() => {
    if (typeof document === 'undefined') return undefined
    const onVisibilityChange = () => setVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [])

  return visible
}

export function LibraryPage() {
  const pageVisible = usePageVisible()
  const currentProjectId = useAppStore((state) => state.currentProjectId)
  const [rootDialogOpen, setRootDialogOpen] = useState(false)
  const [maintenanceBusy, setMaintenanceBusy] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  const rawStatus = searchParams.get('status')
  const status = (
    rawStatus && rawStatus in libraryStatusLabels ? rawStatus : undefined
  ) as LibraryItemStatus | undefined
  const {
    addRootMutation,
    scanMutation,
    parseMutation,
    reparseMutation,
    retryMutation,
    pauseProcessingMutation,
    resumeProcessingMutation,
    supplementMutation,
  } = useLibraryActions()

  const rootsQuery = useQuery({
    queryKey: ['library', 'roots', currentProjectId],
    queryFn: () => listLibraryRoots(currentProjectId),
  })
  const processingQuery = useQuery({
    queryKey: ['library', 'processing'],
    queryFn: getLibraryProcessingState,
    refetchInterval: 5000,
  })
  const processingActive =
    processingQuery.data?.available === true && processingQuery.data.paused === false
  const summaryQuery = useQuery({
    queryKey: ['library', 'summary', currentProjectId],
    queryFn: () => getLibrarySummary(currentProjectId),
    refetchInterval: (query) =>
      shouldPollLibrary(query.state.data, pageVisible, processingActive) ? 2_000 : false,
  })
  const polling = shouldPollLibrary(summaryQuery.data, pageVisible, processingActive)
  const itemsQuery = useQuery({
    queryKey: ['library', 'items', { status: status ?? null, project: currentProjectId }],
    queryFn: () => getLibraryItems({ status, projectId: currentProjectId, limit: 100, offset: 0 }),
    refetchInterval: polling ? 2_000 : false,
  })

  const summary = summaryQuery.data
  const processingState = processingQuery.data
  const total = useMemo(
    () => (summary ? Object.values(summary).reduce((sum, count) => sum + count, 0) : 0),
    [summary],
  )
  const processing = summary
    ? summary.PROBING + summary.SCENE_DETECTION + summary.FRAME_EXTRACTION
    : 0

  const loading =
    rootsQuery.isPending ||
    processingQuery.isPending ||
    summaryQuery.isPending ||
    itemsQuery.isPending
  const hardError =
    rootsQuery.error ?? processingQuery.error ?? summaryQuery.error ?? itemsQuery.error

  function setStatus(next: LibraryItemStatus | undefined) {
    if (next === undefined) {
      if (searchParams.has('status')) setSearchParams({}, { replace: true })
    } else {
      setSearchParams({ status: next }, { replace: true })
    }
  }

  if (loading) return <LoadingBlock label="正在读取素材库…" />
  if (hardError) return <ErrorBlock error={hardError} title="素材库读取失败" />

  const processingActionError =
    pauseProcessingMutation.error ?? resumeProcessingMutation.error
  const parsingActionError = parseMutation.error ?? reparseMutation.error ?? retryMutation.error

  return (
    <Flex vertical gap={20}>
      <PageHeader
        title="素材库"
        description="管理本地素材目录和解析状态。素材解析一次后可跨项目复用。"
        extra={
          <Space wrap>
            <Button
              type="primary"
              ghost
              loading={supplementMutation.isPending}
              disabled={maintenanceBusy}
              onClick={() => supplementMutation.mutate()}
            >
              增补解析
            </Button>
            <Button disabled={maintenanceBusy} onClick={() => setRootDialogOpen(true)}>添加目录</Button>
            {processingState?.available ? (
              processingState.paused ? (
                <Button
                  loading={resumeProcessingMutation.isPending}
                  disabled={maintenanceBusy}
                  onClick={() => resumeProcessingMutation.mutate()}
                >
                  继续未完成
                </Button>
              ) : (
                <Button
                  loading={pauseProcessingMutation.isPending}
                  disabled={maintenanceBusy}
                  onClick={() => pauseProcessingMutation.mutate()}
                >
                  暂停解析
                </Button>
              )
            ) : null}
            <Button type="primary" disabled={maintenanceBusy} loading={scanMutation.isPending} onClick={() => scanMutation.mutate()}>
              扫描素材
            </Button>
          </Space>
        }
      />

      {!currentProjectId ? (
        <Alert
          showIcon
          type="info"
          message="当前未选择项目"
          description="现在显示的是全部历史素材；新建或选择项目后，素材库与粗剪将只显示该项目的素材。"
        />
      ) : null}

      {processingState && !processingState.available ? (
        <Alert
          showIcon
          type="warning"
          message="尚未配置视频理解 API"
          description="可以扫描素材，但后台不会开始画面提取或 AI 分析。请在设置中配置视频理解服务并重启 ClipAtlas。"
        />
      ) : null}

      {addRootMutation.error ? <ErrorBlock error={addRootMutation.error} title="添加目录失败" /> : null}
      {scanMutation.error ? <ErrorBlock error={scanMutation.error} title="扫描失败" /> : null}
      {parsingActionError ? <ErrorBlock error={parsingActionError} title="解析失败" /> : null}
      {processingActionError ? (
        <ErrorBlock error={processingActionError} title="解析控制失败" />
      ) : null}

      <Card size="small" variant="borderless">
        <LibraryMaintenanceActions
          onBusyChange={setMaintenanceBusy}
          status={status}
          available={processingState?.available === true}
          busy={Boolean(summary && (summary.PROBING + summary.SCENE_DETECTION + summary.FRAME_EXTRACTION > 0))
            || parseMutation.isPending || reparseMutation.isPending}
        />
      </Card>

      <Flex gap={12} wrap>
        <Card size="small" variant="borderless" hoverable
          style={{ cursor: 'pointer' }} onClick={() => setStatus(undefined)}>
          <Statistic title="素材总数" value={total} />
        </Card>
        <Card size="small" variant="borderless" hoverable
          style={{ cursor: 'pointer' }} onClick={() => setStatus('QUEUED')}>
          <Statistic title="等待解析" value={summary?.QUEUED ?? 0} />
        </Card>
        <Card size="small" variant="borderless">
          <Statistic title="解析中" value={processing} />
        </Card>
        <Card size="small" variant="borderless" hoverable
          style={{ cursor: 'pointer' }} onClick={() => setStatus('COMPLETED')}>
          <Statistic title="解析完成" value={summary?.COMPLETED ?? 0} />
        </Card>
        <Card size="small" variant="borderless" hoverable
          style={{ cursor: 'pointer' }} onClick={() => setStatus('FAILED')}>
          <Statistic title="解析失败" value={summary?.FAILED ?? 0} />
        </Card>
      </Flex>

      {processingState?.paused && (summary?.QUEUED ?? 0) > 0 && !maintenanceBusy ? (
        <Alert type="info" showIcon message="后台自动解析已暂停，等待解析的素材不会自动开始。"
          description="“增补解析”自动重试失败素材、并把缺失 OCR/ASR/批注/画面类型的素材放回队列只补缺口，不会重跑已完成部分；“全部重新解析”才会重跑已完成素材。" />
      ) : null}

      <Card title="素材目录" variant="borderless">
        {rootsQuery.data?.length ? (
          <Space wrap>
            {rootsQuery.data.map((root) => (
              <Tag key={root.id}>
                {root.path}{root.recursive ? ' · 含子目录' : ''}
              </Tag>
            ))}
          </Space>
        ) : (
          <Typography.Text type="secondary">尚未添加本地素材目录</Typography.Text>
        )}
      </Card>

      <Card
        title="素材列表"
        variant="borderless"
        extra={
          <Select<LibraryItemStatus>
            aria-label="解析状态"
            allowClear
            virtual={false}
            placeholder="全部状态"
            value={status}
            style={{ width: 160 }}
            onChange={(value) => setStatus(value)}
            options={Object.entries(libraryStatusLabels).map(([value, label]) => ({
              value: value as LibraryItemStatus,
              label,
            }))}
          />
        }
      >
        <LibraryItemTable
          items={itemsQuery.data ?? []}
          status={status}
          loading={itemsQuery.isFetching && !itemsQuery.isPending}
          parsingAvailable={processingState?.available === true && !maintenanceBusy}
          parsingItemId={parseMutation.isPending ? parseMutation.variables : null}
          reparsingItemId={reparseMutation.isPending ? reparseMutation.variables : null}
          retryingItemId={retryMutation.isPending ? retryMutation.variables : null}
          onParse={(itemId) => parseMutation.mutate(itemId)}
          onReparse={(itemId) => reparseMutation.mutate(itemId)}
          onRetry={(itemId) => retryMutation.mutate(itemId)}
        />
      </Card>

      <LibraryRootDialog
        open={rootDialogOpen}
        submitting={addRootMutation.isPending}
        onCancel={() => setRootDialogOpen(false)}
        onSubmit={async (input) => {
          await addRootMutation.mutateAsync({ ...input, projectId: currentProjectId })
          setRootDialogOpen(false)
        }}
      />
    </Flex>
  )
}
