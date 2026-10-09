import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Collapse,
  Empty,
  Flex,
  InputNumber,
  Segmented,
  Space,
  Tag,
  Typography,
} from 'antd'
import { useNavigate } from 'react-router-dom'

import { getLibraryItems } from '../../api/library'
import { createRoughCutPlan } from '../../api/roughCut'
import { getNarrationTrack, getProjectScript, listProjectNarrations, type NarrationTrack } from '../../api/speech'
import { ErrorBlock } from '../../components/ErrorBlock'
import { LoadingBlock } from '../../components/LoadingBlock'
import { PageHeader } from '../../components/PageHeader'
import { useAppStore } from '../../stores/useAppStore'
import { formatDuration } from '../../utils/format'
import { timingQualityLabels } from '../../utils/statusMaps'

type MaterialScope = '全部素材' | '指定素材'

const SUPPORTED_TIMING = new Set(['word_exact', 'unit_exact', 'aligned'])

function filenameFromPath(path: string): string {
  const normalized = path.replaceAll('\\', '/')
  return normalized.split('/').filter(Boolean).at(-1) ?? path
}

function narrationSourceLabel(source: NarrationTrack['source_mode']): string {
  if (source === 'tts') return 'AI 配音'
  if (source === 'imported') return '真人旁白'
  return '估算旁白'
}

export function RoughCutPage() {
  const navigate = useNavigate()
  const projectId = useAppStore((state) => state.currentProjectId)
  const [scope, setScope] = useState<MaterialScope>('全部素材')
  const [topK, setTopK] = useState(12)
  const [selectedVideoIds, setSelectedVideoIds] = useState<string[]>([])
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  const narrationsQuery = useQuery({
    queryKey: ['project', projectId, 'narrations'],
    queryFn: () => listProjectNarrations(projectId as string),
    enabled: Boolean(projectId),
  })
  const completedItemsQuery = useQuery({
    queryKey: ['project', projectId, 'library', 'items', 'rough-cut-scope'],
    queryFn: () => getLibraryItems({ status: 'COMPLETED', projectId, limit: 500, offset: 0 }),
    enabled: Boolean(projectId),
  })

  const createPlan = useMutation({
    mutationFn: createRoughCutPlan,
    onSuccess: (plan) => {
      void navigate(`/rough-cut/${plan.id}`)
    },
  })

  const activeTrack = useMemo(() => {
    const history = narrationsQuery.data
    if (!history?.active_track_id) return null
    return history.tracks.find((track) => track.id === history.active_track_id) ?? null
  }, [narrationsQuery.data])
  const narrationDetailQuery = useQuery({
    queryKey: ['narration', activeTrack?.id],
    queryFn: () => getNarrationTrack(activeTrack!.id),
    enabled: Boolean(activeTrack),
  })
  useEffect(() => {
    if (!createPlan.isPending) return
    const started = Date.now()
    const timer = window.setInterval(() => setElapsedSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [createPlan.isPending])
  const scriptQuery = useQuery({
    queryKey: ['project', projectId, 'script'],
    queryFn: () => getProjectScript(projectId as string), enabled: Boolean(projectId),
  })

  if (!projectId) {
    return (
      <Flex vertical gap={20}>
        <PageHeader
          title="剪辑草稿"
          description="剪辑草稿属于当前项目，请先在顶部选择或创建项目。"
        />
        <Card variant="borderless">
          <Empty description="请先选择或创建项目" />
        </Card>
      </Flex>
    )
  }

  const activeProjectId: string = projectId
  const loading = narrationsQuery.isPending || completedItemsQuery.isPending
  const hardError = narrationsQuery.error ?? completedItemsQuery.error
  if (loading) return <LoadingBlock label="正在读取剪辑草稿前置状态…" />
  if (hardError) return <ErrorBlock error={hardError} title="剪辑草稿状态读取失败" />

  const completedItems = (completedItemsQuery.data ?? []).filter((item) => Boolean(item.video_id))
  const importedTrackOnly =
    activeTrack?.source_mode === 'imported' && activeTrack.timing_quality === 'track_only'
  const timingReady = activeTrack
    ? SUPPORTED_TIMING.has(activeTrack.timing_quality) || importedTrackOnly
    : false
  const selectedScopeReady = scope === '全部素材' || selectedVideoIds.length > 0
  const narrationScript = narrationDetailQuery.data?.script ??
    narrationDetailQuery.data?.units.map((unit) => unit.text).join('\n') ?? ''
  const scriptMismatch = Boolean(scriptQuery.data?.script_hash &&
    scriptQuery.data.script_hash !== activeTrack?.script_hash)
  const canGenerate = Boolean(activeTrack && narrationScript.trim() && !scriptMismatch &&
    narrationDetailQuery.isSuccess && scriptQuery.isSuccess &&
    timingReady && selectedScopeReady && topK >= 1 && topK <= 100 && !createPlan.isPending)

  function submitPlan() {
    if (!canGenerate) return
    setElapsedSeconds(0)
    const input = {
      project_id: activeProjectId,
      top_k: topK,
      ...(scope === '指定素材' ? { video_ids: selectedVideoIds } : {}),
    }
    createPlan.mutate(input)
  }

  return (
    <Flex vertical gap={20}>
      <PageHeader
        title="剪辑草稿"
        description="根据当前旁白和素材生成可继续替换、裁切和调整的剪辑草稿。"
      />

      <Card title="当前旁白" variant="borderless">
        {activeTrack ? (
          <Flex vertical gap={10}>
            <Flex gap={8} wrap align="center">
              <Tag color="success">当前激活</Tag>
              <Tag>{narrationSourceLabel(activeTrack.source_mode)}</Tag>
              <Typography.Text strong>{formatDuration(activeTrack.duration_ms)}</Typography.Text>
              <Typography.Text>{timingQualityLabels[activeTrack.timing_quality]}</Typography.Text>
              <Typography.Text type="secondary">{`修订 ${activeTrack.revision}`}</Typography.Text>
            </Flex>
            {importedTrackOnly ? (
              <Alert
                showIcon
                type="warning"
                message="生成前将自动识别真人旁白，并与文案逐段对齐。"
                description="首次需要识别音频；对齐成功后按当前讲述内容选画面。文案与音频不匹配时会提示具体问题。"
              />
            ) : !timingReady ? (
              <Alert
                showIcon
                type="warning"
                message={
                  activeTrack.timing_quality === 'track_only'
                    ? '当前旁白只有总时长，缺少可驱动剪辑草稿的句级或词级时间信息。'
                    : '当前旁白时长仍是估算值，不能驱动剪辑草稿。'
                }
                description="请回到“文案与旁白”，生成带精确时间信息的 AI 配音，或导入并完成对齐的真人旁白。"
              />
            ) : null}
          </Flex>
        ) : (
          <Alert
            showIcon
            type="warning"
            message="请先在“文案与旁白”中激活一个旁白"
            description="剪辑草稿以当前激活旁白的真实音频时长为唯一时长权威。"
          />
        )}
      </Card>

      <Card title="当前旁白对应文案" variant="borderless">
        {narrationDetailQuery.isFetching ? <LoadingBlock label="正在读取文案…" /> : null}
        {narrationDetailQuery.error ? <ErrorBlock error={narrationDetailQuery.error} title="文案读取失败" /> : null}
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', maxHeight: 280, overflow: 'auto' }}>
          {narrationScript || '当前旁白没有关联文案，请到“文案与旁白”保存并关联。'}
        </Typography.Paragraph>
        {scriptMismatch ? <Alert type="warning" showIcon message="已保存文案与当前旁白不一致，请先关联真人旁白或重新生成配音。" /> : null}
        {scriptQuery.error ? <ErrorBlock error={scriptQuery.error} title="已保存文案读取失败" /> : null}
      </Card>

      <Card title="素材范围" variant="borderless">
        <Flex vertical gap={14}>
          <Segmented<MaterialScope>
            disabled={createPlan.isPending}
            value={scope}
            options={['全部素材', '指定素材']}
            onChange={setScope}
          />
          <Typography.Text type="secondary">
            {scope === '全部素材'
              ? '后端只在当前项目已完成语义处理的素材中检索。下面列出当前项目可用素材。'
              : '只在勾选的视频中检索；所选 video_id 将原样交给后端 Planner。'}
          </Typography.Text>

          {completedItems.length ? (
            <Collapse
              defaultActiveKey={[]}
              items={[{
                key: 'videos',
                label: `展开当前项目素材（${completedItems.length} 个视频）`,
                children: <Checkbox.Group
                  value={selectedVideoIds}
                  disabled={scope === '指定素材' ? createPlan.isPending : true}
                  onChange={(values) => setSelectedVideoIds(values.map(String))}
                  style={{ width: '100%' }}
                >
                  <Flex vertical gap={8} style={{ maxHeight: 420, overflowY: 'auto' }}>
                    {completedItems.map((item) => (
                      <Checkbox key={item.id} value={item.video_id as string}>
                        <Space size={8} wrap>
                          <Typography.Text strong>{filenameFromPath(item.source_path)}</Typography.Text>
                          <Typography.Text type="secondary">{item.source_path}</Typography.Text>
                        </Space>
                      </Checkbox>
                    ))}
                  </Flex>
                </Checkbox.Group>,
              }]}
            />
          ) : null}
          {completedItems.length === 0 ? (
            <Empty description="暂无已完成处理且可用于生成草稿的素材" />
          ) : null}

          {scope === '指定素材' && selectedVideoIds.length === 0 ? (
            <Typography.Text type="warning">请至少选择一个素材视频。</Typography.Text>
          ) : null}
        </Flex>
      </Card>

      <Card title="检索候选数量" variant="borderless">
        <Flex gap={12} align="center" wrap>
          <Typography.Text>每个文案段落检索 Top-K</Typography.Text>
          <InputNumber
            aria-label="Top-K"
            disabled={createPlan.isPending}
            min={1}
            max={100}
            precision={0}
            value={topK}
            onChange={(value) => setTopK(value ?? 12)}
          />
          <Typography.Text type="secondary">
            默认 12。这里只控制候选数量；语义、动作、场景、情绪、时长、质量和连续性权重由后端 Planner 统一管理。
          </Typography.Text>
        </Flex>
      </Card>

      <Card variant="borderless" data-testid="generation-status"
        style={createPlan.isPending || createPlan.error ? { position: 'sticky', bottom: 0, zIndex: 2, boxShadow: '0 -4px 16px #0000000d' } : undefined}>
        <Flex vertical gap={12}>
        {createPlan.isPending ? <div role="status" aria-live="polite">
          <Alert type="info" showIcon message="正在生成剪辑草稿…"
            description={`已用时 ${formatDuration(elapsedSeconds * 1000)}。正在对齐旁白、逐段检索并复核画面，可能需要几分钟，请保持本页打开。`} />
        </div> : null}
        {createPlan.error ? <>
          <ErrorBlock error={createPlan.error} title="剪辑草稿生成失败" />
          <Typography.Text type="secondary">本次没有生成新方案，已有旁白和素材索引保留。修复问题后可点击下方按钮重试。</Typography.Text>
        </> : null}
        <Flex justify="space-between" align="center" gap={12} wrap>
          <Typography.Text type="secondary">
            生成后直接进入剪辑草稿，可替换素材、裁切、拆分并导出剪映草稿。
          </Typography.Text>
          <Button
            aria-label={createPlan.isError ? '重新生成剪辑草稿' : '生成剪辑草稿'}
            type="primary"
            size="large"
            loading={createPlan.isPending}
            disabled={!canGenerate}
            onClick={submitPlan}
          >
            {createPlan.isPending ? '正在生成…' : createPlan.isError ? '重新生成剪辑草稿' : '生成剪辑草稿'}
          </Button>
        </Flex>
        </Flex>
      </Card>
    </Flex>
  )
}
