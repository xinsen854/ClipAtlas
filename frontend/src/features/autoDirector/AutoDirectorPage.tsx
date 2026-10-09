import { useEffect, useState, type DragEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Segmented,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import { useNavigate } from 'react-router-dom'

import {
  analyzeStory,
  confirmStoryOutline,
  getAutoDirectorReadiness,
  listStoryOutlines,
  updateStoryOutline,
  type StoryOutline,
  type StoryOutlineNode,
  type StoryRole,
} from '../../api/autoDirector'
import { createRoughCutPlan, type CreateRoughCutInput } from '../../api/roughCut'
import { listProjectSpeechProfiles } from '../../api/speech'
import { ErrorBlock } from '../../components/ErrorBlock'
import { useAppStore } from '../../stores/useAppStore'
import { DEFAULT_STORY_SKILL } from './defaultStorySkill'

const { Text, Title, Paragraph } = Typography
const STORY_SKILL_MAX_BYTES = 200_000
const STORY_SKILL_SUFFIX = /\.(md|txt|json|ya?ml)$/i

const roleOptions: { value: StoryRole; label: string }[] = [
  { value: 'hook', label: '钩子' },
  { value: 'setup', label: '铺垫' },
  { value: 'development', label: '发展' },
  { value: 'reversal', label: '反转' },
  { value: 'payoff', label: '高潮 / 回报' },
  { value: 'ending', label: '结尾' },
  { value: 'other', label: '其他' },
]

type LoadedSkill = { name: string; content: string; builtin: boolean }
type VoiceStrategy = NonNullable<CreateRoughCutInput['voice_strategy']>

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function cloneNodes(nodes: StoryOutlineNode[]): StoryOutlineNode[] {
  return nodes.map((node) => ({
    ...node,
    evidence: node.evidence.map((evidence) => ({ ...evidence })),
  }))
}

export function AutoDirectorPage() {
  const navigate = useNavigate()
  const projectId = useAppStore((state) => state.currentProjectId)
  const queryClient = useQueryClient()
  const [skill, setSkill] = useState<LoadedSkill>({ ...DEFAULT_STORY_SKILL, builtin: true })
  const [skillError, setSkillError] = useState<string | null>(null)
  const [outline, setOutline] = useState<StoryOutline | null>(null)
  const [summary, setSummary] = useState('')
  const [hookRationale, setHookRationale] = useState('')
  const [nodes, setNodes] = useState<StoryOutlineNode[]>([])
  const [dirty, setDirty] = useState(false)
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [voiceStrategy, setVoiceStrategy] = useState<VoiceStrategy>('original_audio')
  const [speechProfileId, setSpeechProfileId] = useState<string>()

  const readinessQuery = useQuery({
    queryKey: ['auto-director-readiness', projectId],
    queryFn: () => getAutoDirectorReadiness(projectId as string),
    enabled: Boolean(projectId),
    retry: false,
  })

  const outlinesQuery = useQuery({
    queryKey: ['auto-director-outlines', projectId],
    queryFn: () => listStoryOutlines(projectId as string),
    enabled: Boolean(projectId),
    retry: false,
  })

  const speechProfilesQuery = useQuery({
    queryKey: ['project', projectId, 'speech-profiles', 'auto-director'],
    queryFn: () => listProjectSpeechProfiles(projectId as string),
    enabled: Boolean(projectId && outline?.status === 'confirmed' && voiceStrategy === 'tts'),
    retry: false,
  })

  function adoptOutline(next: StoryOutline): void {
    setOutline(next)
    setSummary(next.summary)
    setHookRationale(next.hook_rationale)
    setNodes(cloneNodes(next.nodes).sort((a, b) => a.order - b.order))
    setDirty(false)
  }

  useEffect(() => {
    setOutline(null)
    setSummary('')
    setHookRationale('')
    setNodes([])
    setDirty(false)
    setVoiceStrategy('original_audio')
    setSpeechProfileId(undefined)
  }, [projectId])

  useEffect(() => {
    if (!outline && outlinesQuery.data?.length) {
      adoptOutline(outlinesQuery.data[0])
    }
  }, [outline, outlinesQuery.data])

  useEffect(() => {
    if (voiceStrategy !== 'tts') return
    const profiles = speechProfilesQuery.data ?? []
    if (profiles.some((profile) => profile.id === speechProfileId)) return
    setSpeechProfileId(profiles.find((profile) => profile.locked)?.id ?? profiles[0]?.id)
  }, [speechProfileId, speechProfilesQuery.data, voiceStrategy])

  const analyzeMutation = useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error('请先选择项目')
      return analyzeStory({
        projectId,
        skillName: skill.name,
        skillContent: skill.content,
      })
    },
    onSuccess: async (next) => {
      adoptOutline(next)
      await queryClient.invalidateQueries({ queryKey: ['auto-director-outlines', projectId] })
    },
  })

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!projectId || !outline) throw new Error('当前没有可保存的故事简纲')
      return updateStoryOutline({
        projectId,
        outlineId: outline.id,
        summary,
        hookRationale,
        nodes: nodes.map(({ id, title, summary: nodeSummary, role, estimated_duration_ms }) => ({
          id,
          title,
          summary: nodeSummary,
          role,
          estimated_duration_ms,
        })),
      })
    },
    onSuccess: async (next) => {
      adoptOutline(next)
      await queryClient.invalidateQueries({ queryKey: ['auto-director-outlines', projectId] })
    },
  })

  const confirmMutation = useMutation({
    mutationFn: async () => {
      if (!projectId || !outline) throw new Error('当前没有可确认的故事简纲')
      let target = outline
      if (dirty) {
        target = await saveMutation.mutateAsync()
      }
      return confirmStoryOutline({ projectId, outlineId: target.id })
    },
    onSuccess: async (next) => {
      adoptOutline(next)
      await queryClient.invalidateQueries({ queryKey: ['auto-director-outlines', projectId] })
    },
  })

  const executeMutation = useMutation({
    mutationFn: async () => {
      if (!projectId || !outline || outline.status !== 'confirmed') {
        throw new Error('请先确认 Story Outline')
      }
      if (voiceStrategy === 'tts' && !speechProfileId) {
        throw new Error('请选择现有 TTS 配音方案')
      }
      return createRoughCutPlan({
        project_id: projectId,
        story_outline_id: outline.id,
        voice_strategy: voiceStrategy,
        ...(voiceStrategy === 'tts' ? { speech_profile_id: speechProfileId } : {}),
      })
    },
    onSuccess: (plan) => {
      void navigate(`/rough-cut/${encodeURIComponent(plan.id)}`)
    },
  })

  async function loadSkill(file: File | undefined): Promise<void> {
    if (!file) return
    setSkillError(null)
    if (!STORY_SKILL_SUFFIX.test(file.name)) {
      setSkillError('Story Skill 仅支持 .md / .txt / .json / .yaml / .yml')
      return
    }
    if (file.size > STORY_SKILL_MAX_BYTES) {
      setSkillError('Story Skill 文件不能超过 200 KB')
      return
    }
    const content = (await file.text()).trim()
    if (!content) {
      setSkillError('Story Skill 内容不能为空')
      return
    }
    setSkill({ name: file.name, content, builtin: false })
  }

  function restoreDefaultSkill(): void {
    setSkill({ ...DEFAULT_STORY_SKILL, builtin: true })
    setSkillError(null)
  }

  function updateNode(index: number, patch: Partial<StoryOutlineNode>): void {
    setNodes((current) =>
      current.map((node, nodeIndex) => (nodeIndex === index ? { ...node, ...patch } : node)),
    )
    setDirty(true)
  }

  function moveNode(from: number, to: number): void {
    if (to < 0 || to >= nodes.length || from === to) return
    setNodes((current) => {
      const next = [...current]
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      return next.map((node, order) => ({ ...node, order }))
    })
    setDirty(true)
  }

  function deleteNode(index: number): void {
    setNodes((current) =>
      current.filter((_, nodeIndex) => nodeIndex !== index).map((node, order) => ({ ...node, order })),
    )
    setDirty(true)
  }

  function handleDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault()
    void loadSkill(event.dataTransfer.files?.[0])
  }

  const mutationError = analyzeMutation.error ?? saveMutation.error ?? confirmMutation.error
  const busy = analyzeMutation.isPending || saveMutation.isPending || confirmMutation.isPending || executeMutation.isPending
  const readiness = readinessQuery.data
  const canAnalyze = Boolean(projectId && readiness?.ready && !busy)
  const canExecute = Boolean(
    projectId && outline?.status === 'confirmed' && !executeMutation.isPending &&
    (voiceStrategy === 'original_audio' || speechProfileId),
  )

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div>
        <Title level={2} style={{ marginBottom: 4 }}>自动编导</Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          直接读取当前项目已经解析好的素材事实，用可替换 Story Skill 组织故事简纲；确认后选择声音来源并进入现有粗剪链路。
        </Paragraph>
      </div>

      {!projectId ? <Alert type="warning" showIcon message="请先选择项目" /> : null}

      <Card title="1. 当前项目素材 readiness" size="small">
        {readinessQuery.isLoading ? <Text>正在读取素材状态…</Text> : null}
        {readinessQuery.error ? <Alert type="error" showIcon message="素材状态读取失败" description={errorText(readinessQuery.error)} /> : null}
        {readiness ? (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Space wrap>
              <Tag color={readiness.ready ? 'success' : 'warning'}>已完成素材 {readiness.video_count} 个</Tag>
              <Tag color={readiness.ready ? 'success' : 'default'}>证据 {readiness.evidence_count} 条</Tag>
              <Tag>画面 {readiness.visual_count}</Tag>
              <Tag>口播 {readiness.asr_count}</Tag>
              <Tag>OCR {readiness.ocr_count}</Tag>
            </Space>
            {!readiness.ready && readiness.message ? <Alert type="warning" showIcon message={readiness.message} /> : null}
            {readiness.warnings.length ? <Text type="secondary">{readiness.warnings.join('；')}</Text> : null}
          </Space>
        ) : null}
      </Card>

      <Card title="2. Story Skill" size="small">
        <div
          onDragOver={(event) => event.preventDefault()}
          onDrop={handleDrop}
          style={{ border: '1px dashed #b8aaa0', borderRadius: 8, padding: 20, background: '#fffdf9' }}
        >
          <Space direction="vertical" size={8}>
            <Space wrap>
              <Text strong>{skill.builtin ? DEFAULT_STORY_SKILL.label : skill.name}</Text>
              <Tag color={skill.builtin ? 'success' : 'processing'}>{skill.builtin ? '内置 · 默认启用' : '自定义'}</Tag>
            </Space>
            <Text type="secondary">
              {skill.builtin ? DEFAULT_STORY_SKILL.description : '当前使用已上传的编导规则，仅按文本读取，不执行任何代码。'}
            </Text>
            <Space wrap>
              <span>替换为自定义 Skill</span>
              <label>
                <input
                aria-label="替换为自定义 Story Skill"
                type="file"
                accept=".md,.txt,.json,.yaml,.yml"
                style={{ display: 'none' }}
                onChange={(event) => void loadSkill(event.target.files?.[0])}
                />
                <Button size="small">选择文件</Button>
              </label>
              <Text type="secondary">{skill.builtin ? '未选择文件' : skill.name}</Text>
            </Space>
            {!skill.builtin ? (
              <Button size="small" onClick={restoreDefaultSkill}>恢复内置 Skill</Button>
            ) : null}
            {skillError ? <Alert type="error" showIcon message={skillError} /> : null}
          </Space>
        </div>
        <Space style={{ marginTop: 12 }}>
          <Button type="primary" disabled={!canAnalyze} loading={analyzeMutation.isPending} onClick={() => analyzeMutation.mutate()}>
            {outline ? '重新分析' : '分析故事'}
          </Button>
          {outline ? <Text type="secondary">重新分析会创建新 revision，不覆盖当前有效故事简纲。</Text> : null}
        </Space>
      </Card>

      {mutationError ? <ErrorBlock error={mutationError} title="自动编导操作失败" /> : null}

      <Card
        title="3. 故事简纲"
        size="small"
        extra={outline ? (
          <Space>
            <Tag>Revision {outline.revision}</Tag>
            <Tag color={outline.status === 'confirmed' ? 'success' : 'processing'}>{outline.status === 'confirmed' ? '已确认' : '草稿'}</Tag>
          </Space>
        ) : null}
      >
        {!outline ? <Empty description="分析 Story Skill 后，这里显示 Evidence First 故事简纲" /> : (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {(outlinesQuery.data?.length ?? 0) > 1 ? (
              <Select
                style={{ width: 240 }}
                value={outline.id}
                options={(outlinesQuery.data ?? []).map((item) => ({
                  value: item.id,
                  label: `Revision ${item.revision}${item.status === 'confirmed' ? ' · 已确认' : ''}`,
                }))}
                onChange={(id) => {
                  const selected = outlinesQuery.data?.find((item) => item.id === id)
                  if (selected) adoptOutline(selected)
                }}
              />
            ) : null}

            {outline.warnings.length ? (
              <Alert type="warning" showIcon message="素材证据限制" description={outline.warnings.join('；')} />
            ) : null}

            <div>
              <Text strong>项目故事摘要</Text>
              <Input.TextArea
                value={summary}
                autoSize={{ minRows: 2, maxRows: 6 }}
                disabled={outline.status === 'confirmed'}
                onChange={(event) => { setSummary(event.target.value); setDirty(true) }}
              />
            </div>
            <div>
              <Text strong>钩子理由</Text>
              <Input.TextArea
                value={hookRationale}
                autoSize={{ minRows: 2, maxRows: 5 }}
                disabled={outline.status === 'confirmed'}
                onChange={(event) => { setHookRationale(event.target.value); setDirty(true) }}
              />
            </div>

            {nodes.map((node, index) => (
              <Card
                key={node.id}
                size="small"
                draggable={outline.status !== 'confirmed'}
                onDragStart={() => setDragIndex(index)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => {
                  if (dragIndex !== null) moveNode(dragIndex, index)
                  setDragIndex(null)
                }}
                title={`节点 ${index + 1}`}
                extra={outline.status !== 'confirmed' ? (
                  <Space>
                    <Button size="small" aria-label={`节点 ${index + 1} 上移`} disabled={index === 0} onClick={() => moveNode(index, index - 1)}>上移</Button>
                    <Button size="small" aria-label={`节点 ${index + 1} 下移`} disabled={index === nodes.length - 1} onClick={() => moveNode(index, index + 1)}>下移</Button>
                    <Button danger size="small" aria-label={`删除节点 ${index + 1}`} onClick={() => deleteNode(index)}>删除</Button>
                  </Space>
                ) : null}
              >
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Input
                    value={node.title}
                    disabled={outline.status === 'confirmed'}
                    onChange={(event) => updateNode(index, { title: event.target.value })}
                  />
                  <Input.TextArea
                    value={node.summary}
                    autoSize={{ minRows: 2, maxRows: 6 }}
                    disabled={outline.status === 'confirmed'}
                    onChange={(event) => updateNode(index, { summary: event.target.value })}
                  />
                  <Space wrap>
                    <Select
                      style={{ width: 140 }}
                      value={node.role}
                      disabled={outline.status === 'confirmed'}
                      options={roleOptions}
                      onChange={(role: StoryRole) => updateNode(index, { role })}
                    />
                    <Input
                      style={{ width: 180 }}
                      type="number"
                      min={1}
                      suffix="ms"
                      value={node.estimated_duration_ms}
                      disabled={outline.status === 'confirmed'}
                      onChange={(event) => updateNode(index, { estimated_duration_ms: Math.max(1, Number(event.target.value) || 1) })}
                    />
                  </Space>
                  <details>
                    <summary>查看素材证据（{node.evidence.length}）</summary>
                    <Space direction="vertical" size={6} style={{ width: '100%', marginTop: 8 }}>
                      {node.evidence.map((evidence) => (
                        <div key={evidence.evidence_id} style={{ borderLeft: '3px solid #d8ccc3', paddingLeft: 10 }}>
                          <Text>{evidence.text}</Text><br />
                          <Text type="secondary">
                            {evidence.source_name || evidence.video_id} · {evidence.start_ms}–{evidence.end_ms} ms · {evidence.kind}
                          </Text>
                        </div>
                      ))}
                    </Space>
                  </details>
                </Space>
              </Card>
            ))}

            {nodes.length === 0 ? <Alert type="warning" showIcon message="故事简纲至少需要保留一个节点才能保存或确认" /> : null}
            <Space wrap>
              <Button
                disabled={outline.status === 'confirmed' || !dirty || nodes.length === 0 || busy}
                loading={saveMutation.isPending}
                onClick={() => saveMutation.mutate()}
              >
                保存故事简纲修订
              </Button>
              <Button
                type="primary"
                disabled={outline.status === 'confirmed' || nodes.length === 0 || busy}
                loading={confirmMutation.isPending}
                onClick={() => confirmMutation.mutate()}
              >
                确认故事简纲
              </Button>
              <Text type="secondary">确认只冻结当前故事简纲 revision；确认后再选择声音策略。</Text>
            </Space>
          </Space>
        )}
      </Card>

      {outline?.status === 'confirmed' ? (
        <Card title="4. 声音策略与粗剪" size="small">
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Segmented<VoiceStrategy>
              aria-label="声音策略"
              value={voiceStrategy}
              disabled={executeMutation.isPending}
              options={[
                { label: '原视频口播', value: 'original_audio' },
                { label: 'TTS 配音', value: 'tts' },
              ]}
              onChange={setVoiceStrategy}
            />

            {voiceStrategy === 'original_audio' ? (
              <Text type="secondary">使用 Story 节点已有 ASR 对应的真实原视频语音；没有 ASR 的节点仍按 Visual-only 保留。</Text>
            ) : null}

            {voiceStrategy === 'tts' ? (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {speechProfilesQuery.isLoading ? <Text>正在读取现有配音方案…</Text> : null}
                {speechProfilesQuery.error ? (
                  <Alert type="error" showIcon message="配音方案读取失败" description={errorText(speechProfilesQuery.error)} />
                ) : null}
                {speechProfilesQuery.data?.length ? (
                  <Select
                    aria-label="TTS 配音方案"
                    style={{ width: 'min(420px, 100%)' }}
                    value={speechProfileId}
                    disabled={executeMutation.isPending}
                    options={speechProfilesQuery.data.map((profile) => ({
                      value: profile.id,
                      label: `${profile.provider} · ${profile.voice_id}`,
                    }))}
                    onChange={setSpeechProfileId}
                  />
                ) : null}
                {speechProfilesQuery.isSuccess && !speechProfilesQuery.data.length ? (
                  <Alert type="warning" showIcon message="当前项目还没有 TTS 配音方案" description="请先在文案与旁白中创建配音方案。" />
                ) : null}
                <Text type="secondary">使用已确认的故事节点文字生成配音。</Text>
              </Space>
            ) : null}

            {executeMutation.error ? (
              <Alert type="error" showIcon message="故事粗剪生成失败" description={errorText(executeMutation.error)} />
            ) : null}

            <Space wrap>
              <Button
                type="primary"
                size="large"
                disabled={!canExecute}
                loading={executeMutation.isPending}
                onClick={() => executeMutation.mutate()}
              >
                生成故事粗剪
              </Button>
              <Text type="secondary">生成完成后进入粗剪检查页。</Text>
            </Space>
          </Space>
        </Card>
      ) : null}
    </Space>
  )
}
