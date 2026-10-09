import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
  Flex,
  Input,
  Segmented,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import { Link } from 'react-router-dom'

import {
  listProjectNarrations,
  listProjectSpeechProfiles,
  listSpeechProviders,
  listSpeechVoices,
  getProjectScript,
  saveProjectScript,
  type NarrationTrack,
  type SpeechProfile,
} from '../../api/speech'
import { ErrorBlock } from '../../components/ErrorBlock'
import { LoadingBlock } from '../../components/LoadingBlock'
import { PageHeader } from '../../components/PageHeader'
import { useAppStore } from '../../stores/useAppStore'
import { formatDuration } from '../../utils/format'
import { timingQualityLabels } from '../../utils/statusMaps'
import { SpeechProfileForm } from './SpeechProfileForm'
import { useNarrationActions } from './useNarrationActions'

type NarrationMode = 'AI 配音' | '上传真人旁白'

function narrationSourceLabel(source: NarrationTrack['source_mode']): string {
  if (source === 'tts') return 'AI 配音'
  if (source === 'imported') return '真人旁白'
  return '估算旁白'
}

function profileLabel(profile: SpeechProfile): string {
  return `${profile.voice_id} · ${profile.provider} · 修订 ${profile.revision}`
}

export function NarrationPage() {
  const projectId = useAppStore((state) => state.currentProjectId)
  const [mode, setMode] = useState<NarrationMode>('AI 配音')
  const [editedScripts, setEditedScripts] = useState<Record<string, string>>({})
  const queryClient = useQueryClient()
  const scriptQuery = useQuery({
    queryKey: ['project', projectId, 'script'],
    queryFn: () => getProjectScript(projectId as string),
    enabled: Boolean(projectId),
  })
  const script = projectId ? editedScripts[projectId] ?? scriptQuery.data?.text ?? '' : ''
  function setScript(text: string) {
    if (projectId) setEditedScripts((current) => ({ ...current, [projectId]: text }))
  }
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null)
  const [providerForVoices, setProviderForVoices] = useState<string | null>(null)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const saveScript = useMutation({
    mutationFn: () => saveProjectScript(projectId as string, script),
    onSuccess: async (result) => {
      const savedProjectId = result.script.project_id
      queryClient.setQueryData(['project', savedProjectId, 'script'], result.script)
      await queryClient.invalidateQueries({ queryKey: ['project', savedProjectId, 'narrations'] })
      await queryClient.invalidateQueries({ queryKey: ['narration'] })
      if (savedProjectId !== useAppStore.getState().currentProjectId) return
      setNotice(result.attached_track_id
        ? '文案已保存并关联到当前旁白；音频和真实时长保持不变。'
        : '文案已保存。请用这份文案导入真人旁白或生成 AI 配音。')
    },
  })
  useEffect(() => { setImportFile(null) }, [projectId])

  const providersQuery = useQuery({
    queryKey: ['speech', 'providers'],
    queryFn: listSpeechProviders,
    enabled: Boolean(projectId),
  })
  const profilesQuery = useQuery({
    queryKey: ['project', projectId, 'speech-profiles'],
    queryFn: () => listProjectSpeechProfiles(projectId as string),
    enabled: Boolean(projectId),
  })
  const narrationsQuery = useQuery({
    queryKey: ['project', projectId, 'narrations'],
    queryFn: () => listProjectNarrations(projectId as string),
    enabled: Boolean(projectId),
  })
  const voicesQuery = useQuery({
    queryKey: ['speech', 'voices', providerForVoices],
    queryFn: () => listSpeechVoices(providerForVoices as string),
    enabled: Boolean(projectId && providerForVoices),
  })

  const actions = useNarrationActions(projectId ?? '')

  useEffect(() => {
    const profiles = profilesQuery.data ?? []
    if (!profiles.length) {
      setSelectedProfileId(null)
      return
    }
    if (!selectedProfileId || !profiles.some((profile) => profile.id === selectedProfileId)) {
      setSelectedProfileId(profiles[0].id)
    }
  }, [profilesQuery.data, selectedProfileId])

  useEffect(() => {
    const providers = providersQuery.data ?? []
    if (!providerForVoices && providers.length) {
      setProviderForVoices(providers[0].name)
    }
  }, [providerForVoices, providersQuery.data])

  const activeTrack = useMemo(() => {
    const history = narrationsQuery.data
    if (!history?.active_track_id) return null
    return history.tracks.find((track) => track.id === history.active_track_id) ?? null
  }, [narrationsQuery.data])

  useEffect(() => {
    if (activeTrack?.source_mode === 'imported') setMode('上传真人旁白')
  }, [activeTrack?.id, activeTrack?.source_mode])

  if (!projectId) {
    return (
      <Flex vertical gap={20}>
        <PageHeader
          title="文案与旁白"
          description="旁白属于项目上下文，请先在顶部选择一个项目。"
        />
        <Card variant="borderless">
          <Empty description="请先选择或创建项目" />
        </Card>
      </Flex>
    )
  }

  const activeProjectId: string = projectId
  const loading = providersQuery.isPending || profilesQuery.isPending || narrationsQuery.isPending
  const hardError = providersQuery.error ?? profilesQuery.error ?? narrationsQuery.error
  if (loading) return <LoadingBlock label="正在读取旁白配置…" />
  if (hardError) return <ErrorBlock error={hardError} title="旁白状态读取失败" />

  const profiles = profilesQuery.data ?? []
  const providers = providersQuery.data ?? []
  const voices = voicesQuery.data ?? []
  const ttsAvailable = providers.length > 0
  const history = narrationsQuery.data
  const actionError =
    actions.createProfile.error ??
    actions.randomizeProfile.error ??
    actions.createTts.error ??
    actions.importTrack.error

  async function createProfile(input: Parameters<typeof actions.createProfile.mutateAsync>[0]) {
    const created = await actions.createProfile.mutateAsync(input)
    setSelectedProfileId(created.id)
    setNotice('语音配置已保存')
  }

  async function randomizeProfile() {
    const selected = profiles.find((profile) => profile.id === selectedProfileId)
    const provider = selected?.provider ?? providerForVoices ?? providers[0]?.name
    if (!provider) return
    const randomized = await actions.randomizeProfile.mutateAsync({
      project_id: activeProjectId,
      provider,
      mode: 'random_all',
      seed: Date.now() % 2_147_483_647,
    })
    setSelectedProfileId(randomized.id)
    setNotice(`已随机生成语音配置：${randomized.voice_id}`)
  }

  async function generateTts() {
    if (!script || !selectedProfileId) return
    const result = await actions.createTts.mutateAsync({
      project_id: activeProjectId,
      script,
      speech_profile_id: selectedProfileId,
    })
    setNotice(`AI 配音已生成并作为当前旁白，真实时长 ${formatDuration(result.track.duration_ms)}`)
  }

  async function importHumanNarration() {
    if (!script || !importFile) return
    const result = await actions.importTrack.mutateAsync({
      projectId: activeProjectId,
      script,
      file: importFile,
    })
    setNotice(`真人旁白已导入并作为当前旁白，真实时长 ${formatDuration(result.track.duration_ms)}`)
  }

  return (
    <Flex vertical gap={20}>
      <PageHeader
        title="文案与旁白"
        description="文案用于生成或对齐旁白。上传或生成后会立即作为当前旁白，用于后续剪辑草稿。"
        extra={<Link to="/narration/batch"><Button type="primary">批量MD与真人旁白</Button></Link>}
      />

      {notice ? <Alert showIcon type="success" message={notice} closable onClose={() => setNotice(null)} /> : null}
      {actionError ? <ErrorBlock error={actionError} title="旁白操作失败" /> : null}
      {saveScript.error ? <ErrorBlock error={saveScript.error} title="文案保存失败" /> : null}
      {scriptQuery.error ? <ErrorBlock error={scriptQuery.error} title="已保存文案读取失败" /> : null}

      <Card title="当前使用的旁白" variant="borderless">
        {activeTrack ? (
          <Flex gap={16} align="center" wrap>
            <Tag color="success">当前使用</Tag>
            <Tag>{narrationSourceLabel(activeTrack.source_mode)}</Tag>
            <Typography.Text strong>{formatDuration(activeTrack.duration_ms)}</Typography.Text>
            <Typography.Text>{timingQualityLabels[activeTrack.timing_quality]}</Typography.Text>
            <Typography.Text type="secondary">{`修订 ${activeTrack.revision}`}</Typography.Text>
          </Flex>
        ) : (
          <Typography.Text type="secondary">尚无旁白。上传或生成后会自动作为当前旁白，无需再次选择。</Typography.Text>
        )}
      </Card>

      <Card title="文案" variant="borderless">
        <Flex vertical gap={10}>
          <label style={{ alignSelf: 'flex-start' }}>
            <input
              aria-label="导入文案文件"
              type="file"
              accept=".txt,.md,.srt,text/plain,text/markdown,application/x-subrip"
              style={{ display: 'none' }}
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void file.text().then(setScript)
              }}
            />
            <Button>导入文案文件</Button>
          </label>
          <Typography.Text type="secondary">支持本地 .txt、.md、.srt 文件，内容会直接载入下方文案框。</Typography.Text>
          <Input.TextArea
            aria-label="旁白文案"
            rows={8}
            value={script}
            placeholder="输入完整旁白文案。生成 TTS 或导入真人旁白时，会原样提交给后端。"
            onChange={(event) => setScript(event.target.value)}
          />
          <Space wrap>
            <Button type="primary" loading={saveScript.isPending}
              disabled={!script.trim()} onClick={() => saveScript.mutate()}>
              保存文案
            </Button>
            <Typography.Text type="secondary">
              {script === scriptQuery.data?.text ? '已保存的文案' : '有未保存的修改'}
            </Typography.Text>
          </Space>
          <Typography.Text type="secondary">
            已有真人旁白时，保存会关联这份文案并保留音频；文案改变会新增旁白修订，原句级对齐需重新制作。AI 配音文案改变后需重新生成配音。
          </Typography.Text>
        </Flex>
      </Card>

      <Card variant="borderless">
        <Segmented<NarrationMode>
          block
          value={mode}
          options={['AI 配音', '上传真人旁白']}
          onChange={setMode}
        />
      </Card>

      {mode === 'AI 配音' ? (
        <Flex vertical gap={16}>
          {!ttsAvailable ? (
            <Alert
              showIcon
              type="warning"
              message="尚未配置 TTS API"
              description="AI 配音当前不可用。请在设置中配置语音服务并重启 ClipAtlas；文案编辑和上传真人旁白仍可使用。"
              action={
                <Link to="/settings">
                  <Button size="small">去设置语音 API</Button>
                </Link>
              }
            />
          ) : null}

          <Card title="选择语音配置" variant="borderless">
            <Flex vertical gap={12}>
              <Flex gap={8} align="center" wrap>
                <Select
                  aria-label="语音配置"
                  style={{ minWidth: 320, flex: '1 1 320px' }}
                  placeholder="请选择语音配置"
                  value={selectedProfileId}
                  options={profiles.map((profile) => ({ value: profile.id, label: profileLabel(profile) }))}
                  onChange={setSelectedProfileId}
                />
                {voices.length ? (
                  <Button
                    aria-label="随机"
                    loading={actions.randomizeProfile.isPending}
                    onClick={() => void randomizeProfile()}
                  >
                    随机
                  </Button>
                ) : null}
                <Button
                  type="primary"
                  loading={actions.createTts.isPending}
                  disabled={!ttsAvailable || !script || !selectedProfileId}
                  onClick={() => void generateTts()}
                >
                  生成 AI 配音
                </Button>
              </Flex>

              {profiles.length ? (
                <Space size={[6, 6]} wrap>
                  {profiles.map((profile) => (
                    <Tag key={profile.id} color={profile.id === selectedProfileId ? 'processing' : undefined}>
                      {profile.voice_id} · {profile.gender_constraint ?? '不限'} · {profile.speed ?? 1}x ·{' '}
                      {profile.locked ? '已锁定' : '未锁定'}
                    </Tag>
                  ))}
                </Space>
              ) : (
                <Typography.Text type="secondary">还没有语音配置，请在下方创建。</Typography.Text>
              )}
            </Flex>
          </Card>

          <Card title="新建语音配置" variant="borderless">
            <SpeechProfileForm
              projectId={activeProjectId}
              providers={providers}
              voices={voices}
              submitting={actions.createProfile.isPending}
              onProviderChange={setProviderForVoices}
              onSubmit={createProfile}
            />
            {voicesQuery.error ? <ErrorBlock error={voicesQuery.error} title="音色列表读取失败" /> : null}
          </Card>
        </Flex>
      ) : (
        <Card title="上传真人旁白" variant="borderless">
          <Flex vertical gap={12}>
            <Space wrap>
              <label>
                <input
                  aria-label="上传旁白音频"
                  type="file"
                  accept="audio/*"
                  style={{ display: 'none' }}
                  onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
                />
                <Button>上传旁白音频</Button>
              </label>
              <Typography.Text type="secondary">{importFile?.name ?? '未选择文件'}</Typography.Text>
            </Space>
            <Typography.Text type="secondary">
              上传的音频会立即作为当前旁白，并由后端规范化、读取真实时长；文案用于后续分段和时间对齐。
            </Typography.Text>
            <Button
              type="primary"
              loading={actions.importTrack.isPending}
              disabled={!script || !importFile}
              onClick={() => void importHumanNarration()}
            >
              上传并使用真人旁白
            </Button>
          </Flex>
        </Card>
      )}

      <Collapse
        items={[
          {
            key: 'narration-history',
            label: (
              <Flex align="center" gap={8}>
                <Typography.Text strong>旁白历史</Typography.Text>
                <Tag>{history?.tracks.length ?? 0} 条</Tag>
              </Flex>
            ),
            children: history?.tracks.length ? (
              <Flex vertical gap={10}>
                {history.tracks.map((track) => {
                  const active = track.id === history.active_track_id
                  return (
                    <Card key={track.id} size="small" variant="outlined">
                      <Flex justify="space-between" align="center" gap={12} wrap>
                        <Space size={[6, 6]} wrap>
                          {active ? <Tag color="success">当前使用</Tag> : null}
                          <Tag>{narrationSourceLabel(track.source_mode)}</Tag>
                          <Typography.Text strong>{formatDuration(track.duration_ms)}</Typography.Text>
                          <Typography.Text>{timingQualityLabels[track.timing_quality]}</Typography.Text>
                          <Typography.Text type="secondary">{`修订 ${track.revision}`}</Typography.Text>
                        </Space>
                      </Flex>
                    </Card>
                  )
                })}
              </Flex>
            ) : (
              <Empty description="尚无旁白轨道" />
            ),
          },
        ]}
        defaultActiveKey={[]}
      />
    </Flex>
  )
}
