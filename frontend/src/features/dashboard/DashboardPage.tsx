import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, Col, Flex, Row, Space, Statistic, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '../../api/errors'
import { getLibrarySummary, listLibraryRoots } from '../../api/library'
import { listProjects } from '../../api/projects'
import { getActiveRoughCutPlan } from '../../api/roughCut'
import { listProjectNarrations } from '../../api/speech'
import { listProjectRulePacks } from '../../api/rules'
import { ErrorBlock } from '../../components/ErrorBlock'
import { LoadingBlock } from '../../components/LoadingBlock'
import { PageHeader } from '../../components/PageHeader'
import { ProjectDialog } from '../projects/ProjectDialog'
import { DeleteProjectButton } from '../projects/DeleteProjectButton'
import { useAppStore } from '../../stores/useAppStore'
import { formatDuration } from '../../utils/format'
import { NextStepCard, type NextStep } from './NextStepCard'

export type DashboardState = {
  hasProject: boolean
  hasActiveRules: boolean
  libraryRootCount: number
  libraryItemCount: number
  libraryNeedsAttention: boolean
  hasActiveNarration: boolean
  activePlanId: string | null
}

export function resolveNextStep(state: DashboardState): NextStep {
  if (!state.hasProject) return { label: '创建项目', path: null }
  if (!state.hasActiveRules) return { label: '设置本批规则', path: '/rules' }
  if (state.libraryRootCount === 0 || state.libraryItemCount === 0) {
    return { label: '添加素材', path: '/library' }
  }
  if (state.libraryNeedsAttention) return { label: '查看素材处理', path: '/library' }
  if (!state.hasActiveNarration) return { label: '准备文案与旁白', path: '/narration' }
  if (!state.activePlanId) return { label: '生成剪辑草稿', path: '/rough-cut' }
  return { label: '继续编辑草稿', path: `/rough-cut/${state.activePlanId}` }
}

function narrationSourceLabel(source: string): string {
  if (source === 'tts') return 'AI 配音'
  if (source === 'imported') return '真人旁白'
  return '估算旁白'
}

export function DashboardPage() {
  const navigate = useNavigate()
  const currentProjectId = useAppStore((state) => state.currentProjectId)
  const setCurrentProjectId = useAppStore((state) => state.setCurrentProjectId)
  const [createProjectOpen, setCreateProjectOpen] = useState(false)

  const projectsQuery = useQuery({ queryKey: ['projects'], queryFn: listProjects })
  const rulesQuery = useQuery({
    queryKey: ['project', currentProjectId, 'rules'],
    queryFn: () => listProjectRulePacks(currentProjectId as string),
    enabled: Boolean(currentProjectId),
  })
  const rootsQuery = useQuery({
    queryKey: ['library', 'roots', currentProjectId],
    queryFn: () => listLibraryRoots(currentProjectId),
  })
  const summaryQuery = useQuery({
    queryKey: ['library', 'summary', currentProjectId],
    queryFn: () => getLibrarySummary(currentProjectId),
  })
  const narrationsQuery = useQuery({
    queryKey: ['project', currentProjectId, 'narrations'],
    queryFn: () => listProjectNarrations(currentProjectId as string),
    enabled: Boolean(currentProjectId),
  })
  const activePlanQuery = useQuery({
    queryKey: ['project', currentProjectId, 'rough-cut', 'active'],
    queryFn: () => getActiveRoughCutPlan(currentProjectId as string),
    enabled: Boolean(currentProjectId),
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false
      return failureCount < 1
    },
  })

  const currentProject =
    projectsQuery.data?.find((project) => project.id === currentProjectId) ?? null
  const summary = summaryQuery.data
  const libraryItemCount = summary
    ? Object.values(summary).reduce((total, count) => total + count, 0)
    : 0
  const processingCount = summary
    ? summary.PROBING + summary.SCENE_DETECTION + summary.FRAME_EXTRACTION
    : 0
  const failedCount = summary?.FAILED ?? 0
  const completedCount = summary?.COMPLETED ?? 0
  const activeNarration = useMemo(() => {
    const history = narrationsQuery.data
    if (!history?.active_track_id) return null
    return history.tracks.find((track) => track.id === history.active_track_id) ?? null
  }, [narrationsQuery.data])

  const activePlanMissing =
    activePlanQuery.isError &&
    activePlanQuery.error instanceof ApiError &&
    activePlanQuery.error.status === 404
  const activePlan = activePlanMissing ? null : (activePlanQuery.data ?? null)

  const loading =
    projectsQuery.isPending ||
    rootsQuery.isPending ||
    summaryQuery.isPending ||
    (Boolean(currentProjectId) && rulesQuery.isPending) ||
    (Boolean(currentProjectId) && narrationsQuery.isPending) ||
    (Boolean(currentProjectId) && activePlanQuery.isPending)

  const hardError =
    projectsQuery.error ??
    rootsQuery.error ??
    summaryQuery.error ??
    rulesQuery.error ??
    narrationsQuery.error ??
    (activePlanMissing ? null : activePlanQuery.error)

  if (loading) return <LoadingBlock label="正在汇总工作台状态…" />
  if (hardError) return <ErrorBlock error={hardError} title="工作台状态读取失败" />

  const nextStep = resolveNextStep({
    hasProject: Boolean(currentProjectId),
    hasActiveRules: Boolean(rulesQuery.data?.some((pack) => pack.status === 'active')),
    libraryRootCount: rootsQuery.data?.length ?? 0,
    libraryItemCount,
    libraryNeedsAttention: (summary?.QUEUED ?? 0) > 0 || processingCount > 0 || failedCount > 0,
    hasActiveNarration: Boolean(activeNarration),
    activePlanId: activePlan?.narration_track_id === activeNarration?.id ? activePlan?.id ?? null : null,
  })

  function continueNextStep() {
    if (nextStep.path) {
      void navigate(nextStep.path)
      return
    }
    setCreateProjectOpen(true)
  }

  return (
    <Flex vertical gap={20}>
      <PageHeader
        title="工作台"
        description="这里不做复杂报表，只告诉你当前进度和最该继续的下一步。"
      />

      <NextStepCard step={nextStep} onContinue={continueNextStep} />

      <Row gutter={[16, 16]}>
        <Col xs={24} md={12} xl={6}>
          <Card title="当前项目" variant="borderless" style={{ height: '100%' }}>
            <Flex align="center" gap={12} wrap style={{ marginBottom: 12 }}>
              <Typography.Title level={4} style={{ margin: 0 }}>
                {currentProject?.name ?? '尚未选择项目'}
              </Typography.Title>
              {currentProject ? <DeleteProjectButton project={currentProject} /> : null}
            </Flex>
            <Typography.Text type="secondary">
              {currentProject?.description || '项目用于保存旁白、粗剪和导出任务上下文。'}
            </Typography.Text>
          </Card>
        </Col>

        <Col xs={24} md={12} xl={6}>
          <Card title="全局素材库" variant="borderless" style={{ height: '100%' }}>
            <Space direction="vertical" size={8}>
              <Statistic title="素材总数" value={libraryItemCount} />
              <Space wrap>
                <Tag>等待解析 {summary?.QUEUED ?? 0}</Tag>
                <Tag color={processingCount > 0 ? 'processing' : 'default'}>处理中 {processingCount}</Tag>
                <Tag color="success">已完成 {completedCount}</Tag>
                <Tag color={failedCount > 0 ? 'error' : 'default'}>失败 {failedCount}</Tag>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col xs={24} md={12} xl={6}>
          <Card title="当前旁白" variant="borderless" style={{ height: '100%' }}>
            {activeNarration ? (
              <Space direction="vertical" size={8}>
                <Tag>{narrationSourceLabel(activeNarration.source_mode)}</Tag>
                <Statistic title="真实时长" value={formatDuration(activeNarration.duration_ms)} />
                <Typography.Text type="secondary">
                  revision {activeNarration.revision}
                </Typography.Text>
              </Space>
            ) : (
              <Typography.Text type="secondary">尚未激活旁白</Typography.Text>
            )}
          </Card>
        </Col>

        <Col xs={24} md={12} xl={6}>
          <Card title="当前粗剪" variant="borderless" style={{ height: '100%' }}>
            {activePlan ? (
              <Space direction="vertical" size={8}>
                <Tag color="processing">revision {activePlan.revision}</Tag>
                <Statistic title="成片时长" value={formatDuration(activePlan.total_duration_ms)} />
                <Typography.Text type="secondary">按当前旁白真实时长生成</Typography.Text>
              </Space>
            ) : (
              <Typography.Text type="secondary">尚未生成剪辑草稿</Typography.Text>
            )}
          </Card>
        </Col>
      </Row>

      <ProjectDialog
        open={createProjectOpen}
        onClose={() => setCreateProjectOpen(false)}
        onSaved={(project) => setCurrentProjectId(project.id)}
      />
    </Flex>
  )
}
