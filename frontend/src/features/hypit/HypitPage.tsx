import {
  AudioOutlined,
  DeleteOutlined,
  PictureOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
  SettingOutlined,
  UploadOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Checkbox,
  Card,
  Divider,
  Empty,
  Flex,
  Form,
  Input,
  Popconfirm,
  Radio,
  Select,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd'

import {
  deleteHypitReference,
  openHypitOutput,
  getHypitBrief,
  getHypitConfig,
  getHypitStatus,
  listHypitBuilds,
  listHypitReferences,
  listHypitInputs,
  startHypit,
  stopHypit,
  submitHypitBuild,
  testHypitConnection,
  updateHypitBuildTitle,
  updateHypitConfig,
  updateHypitBrief,
  uploadHypitInput,
  uploadHypitReference,
  type HypitBuild,
  type HypitConfig,
  type HypitConfigUpdate,
  type HypitReference,
  type HypitInput,
} from '../../api/hypit'
import { ErrorBlock } from '../../components/ErrorBlock'
import { PageHeader } from '../../components/PageHeader'

const CONFIG_KEY = ['hypit', 'config'] as const
const STATUS_KEY = ['hypit', 'status'] as const
const REFERENCES_KEY = ['hypit', 'references'] as const
const INPUTS_KEY = ['hypit', 'inputs'] as const
const BRIEF_KEY = ['hypit', 'brief'] as const
const BUILDS_KEY = ['hypit', 'builds'] as const

type ConnectionMode = 'official' | 'third_party'
type ThirdPartyProvider = 'wavespeed' | 'custom'
type WaveSpeedModel = 'seedance-2' | 'seedance-2.5'

type FormValues = {
  connection_mode: ConnectionMode
  third_party_provider?: ThirdPartyProvider
  model?: WaveSpeedModel
  distribution_root?: string
  workspace?: string
  run_file?: string
  endpoint?: string
  provider_package?: string
  base_url?: string
  base_url_field?: string
  credential_field?: string
  provider_config_json?: string
  api_key?: string
  clear_api_key?: boolean
}

function connectionModeFor(config: HypitConfig): ConnectionMode {
  return config.provider_package === '@hypit/provider-hypihub' ? 'official' : 'third_party'
}

function thirdPartyProviderFor(config: HypitConfig): ThirdPartyProvider {
  return config.provider_package === '@hypit/provider-wavespeed' ? 'wavespeed' : 'custom'
}

function formValues(config: HypitConfig): FormValues {
  return {
    connection_mode: connectionModeFor(config),
    third_party_provider: thirdPartyProviderFor(config),
    model: config.provider_config.selectedModel === 'seedance-2.5' ? 'seedance-2.5' : 'seedance-2',
    distribution_root: config.distribution_root,
    workspace: config.workspace,
    run_file: config.run_file,
    endpoint: config.endpoint,
    provider_package: config.provider_package,
    base_url: config.base_url ?? '',
    base_url_field: config.base_url_field,
    credential_field: config.credential_field,
    provider_config_json: JSON.stringify(config.provider_config, null, 2),
    api_key: '',
    clear_api_key: false,
  }
}

function formatBytes(size: number): string {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function outcomeTag(outcome: string) {
  const labels: Record<string, string> = {
    complete: '已完成',
    failed: '失败',
    cancelled: '已取消',
    open: '生成中',
  }
  const colors: Record<string, string> = {
    complete: 'success',
    failed: 'error',
    cancelled: 'default',
    open: 'processing',
  }
  return <Tag color={colors[outcome]}>{labels[outcome] ?? outcome}</Tag>
}

export function HypitPage() {
  const [form] = Form.useForm<FormValues>()
  const queryClient = useQueryClient()
  const connectionMode = Form.useWatch('connection_mode', form)
  const thirdPartyProvider = Form.useWatch('third_party_provider', form)
  const [formError, setFormError] = useState<Error | null>(null)
  const [buildTitle, setBuildTitle] = useState('')
  const [brief, setBrief] = useState('')
  const [voiceStrategy, setVoiceStrategy] = useState<'original' | 'generated'>('original')
  const [connectionNotice, setConnectionNotice] = useState<{ ok: boolean; message: string } | null>(null)
  const [exportingBuildId, setExportingBuildId] = useState<string | null>(null)
  const [exportError, setExportError] = useState<Error | null>(null)

  const configQuery = useQuery({ queryKey: CONFIG_KEY, queryFn: getHypitConfig })
  const statusQuery = useQuery({
    queryKey: STATUS_KEY,
    queryFn: getHypitStatus,
    refetchInterval: 2_000,
  })
  const referencesQuery = useQuery({ queryKey: REFERENCES_KEY, queryFn: listHypitReferences })
  const inputsQuery = useQuery({ queryKey: INPUTS_KEY, queryFn: listHypitInputs })
  const briefQuery = useQuery({ queryKey: BRIEF_KEY, queryFn: getHypitBrief })
  const buildsQuery = useQuery({
    queryKey: BUILDS_KEY,
    queryFn: listHypitBuilds,
    enabled: statusQuery.data?.configured === true,
  })

  useEffect(() => {
    if (configQuery.data) form.setFieldsValue(formValues(configQuery.data))
  }, [configQuery.data, form])
  useEffect(() => {
    if (briefQuery.data) setBrief(briefQuery.data.text)
  }, [briefQuery.data])

  const saveMutation = useMutation({
    mutationFn: updateHypitConfig,
    onSuccess: (config) => {
      queryClient.setQueryData(CONFIG_KEY, config)
      form.setFieldsValue({ api_key: '', clear_api_key: false })
      void queryClient.invalidateQueries({ queryKey: STATUS_KEY })
      void queryClient.invalidateQueries({ queryKey: BUILDS_KEY })
    },
  })
  const connectionMutation = useMutation({
    mutationFn: testHypitConnection,
    onSuccess: setConnectionNotice,
  })
  const startMutation = useMutation({
    mutationFn: startHypit,
    onSuccess: (status) => queryClient.setQueryData(STATUS_KEY, status),
  })
  const stopMutation = useMutation({
    mutationFn: stopHypit,
    onSuccess: (status) => queryClient.setQueryData(STATUS_KEY, status),
  })
  const uploadMutation = useMutation({
    mutationFn: uploadHypitReference,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: REFERENCES_KEY }),
  })
  const inputMutation = useMutation({
    mutationFn: ({ kind, file }: { kind: HypitInput['kind']; file: File }) => uploadHypitInput(kind, file),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: INPUTS_KEY }),
  })
  const briefMutation = useMutation({
    mutationFn: updateHypitBrief,
    onSuccess: (result) => queryClient.setQueryData(BRIEF_KEY, result),
  })
  const deleteMutation = useMutation({
    mutationFn: deleteHypitReference,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: REFERENCES_KEY }),
  })
  const buildMutation = useMutation({
    mutationFn: () => submitHypitBuild(buildTitle),
    onSuccess: () => {
      setBuildTitle('')
      void queryClient.invalidateQueries({ queryKey: BUILDS_KEY })
    },
  })
  const titleMutation = useMutation({
    mutationFn: ({ buildId, title }: { buildId: string; title: string }) =>
      updateHypitBuildTitle(buildId, title),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: BUILDS_KEY }),
  })

  function selectConnection(mode: ConnectionMode) {
    setConnectionNotice(null)
    form.setFieldsValue({
      connection_mode: mode,
      ...(mode === 'third_party' ? { third_party_provider: 'wavespeed', model: 'seedance-2' } : {}),
    })
  }

  function selectThirdParty(provider: ThirdPartyProvider) {
    setConnectionNotice(null)
    if (provider === 'wavespeed') {
      form.setFieldsValue({ third_party_provider: provider, model: 'seedance-2' })
      return
    }
    form.setFieldsValue({
      third_party_provider: provider,
      endpoint: 'custom.default',
      provider_package: '',
      base_url: '',
      provider_config_json: '{}',
    })
  }

  function providerPreset(values: FormValues) {
    if (values.connection_mode === 'third_party' && values.third_party_provider === 'wavespeed') {
      return {
        endpoint: 'wavespeed.default',
        provider_package: '@hypit/provider-wavespeed',
        base_url: 'https://api.wavespeed.ai/api/v3',
        provider_config: { selectedModel: values.model ?? 'seedance-2', pollIntervalMs: 5000 },
      }
    }
    if (values.connection_mode === 'third_party') {
      const rawConfig = values.provider_config_json?.trim() || '{}'
      const providerConfig = JSON.parse(rawConfig) as unknown
      if (providerConfig === null || Array.isArray(providerConfig) || typeof providerConfig !== 'object') {
        throw new Error('Provider 配置必须是 JSON 对象。')
      }
      return {
        endpoint: values.endpoint?.trim() || 'custom.default',
        provider_package: values.provider_package?.trim() || '',
        base_url: values.base_url?.trim() || null,
        provider_config: providerConfig as Record<string, unknown>,
      }
    }
    return {
      endpoint: 'hypihub.default',
      provider_package: '@hypit/provider-hypihub',
      base_url: 'https://hypit.ai',
      provider_config: {},
    }
  }

  async function save() {
    setFormError(null)
    try {
      const current = configQuery.data
      if (!current) return
      const values = await form.validateFields()
      const preset = providerPreset(values)
      const input: HypitConfigUpdate = {
        distribution_root: values.distribution_root?.trim() || current.distribution_root,
        workspace: values.workspace?.trim() || current.workspace,
        run_file: values.run_file?.trim() || current.run_file,
        endpoint: preset.endpoint,
        provider_package: preset.provider_package,
        base_url: preset.base_url,
        base_url_field: 'baseUrl',
        credential_field: 'apiKey',
        provider_config: preset.provider_config,
        clear_api_key: values.clear_api_key ?? false,
      }
      const apiKey = values.api_key?.trim()
      if (apiKey) input.api_key = apiKey
      await saveMutation.mutateAsync(input)
    } catch (caught) {
      if (caught instanceof Error) setFormError(caught)
    }
  }

  async function testConnection() {
    setConnectionNotice(null)
    const values = form.getFieldsValue()
    const preset = providerPreset(values)
    const apiKey = values.api_key?.trim()
    await connectionMutation.mutateAsync({
      ...(apiKey ? { api_key: apiKey } : {}),
      provider_package: preset.provider_package,
      base_url: preset.base_url ?? undefined,
    })
  }

  const config = configQuery.data
  const status = statusQuery.data
  const operationError =
    saveMutation.error || connectionMutation.error || startMutation.error || stopMutation.error || uploadMutation.error ||
    inputMutation.error || briefMutation.error || deleteMutation.error || buildMutation.error || titleMutation.error || exportError

  async function openBuild(item: HypitBuild) {
    const output = item.targets[0]
    if (!output) return
    setExportError(null)
    setExportingBuildId(item.id)
    try {
      await openHypitOutput(item.id, output)
    } catch (caught) {
      setExportError(caught instanceof Error ? caught : new Error(String(caught)))
    } finally {
      setExportingBuildId(null)
    }
  }

  const referenceColumns = [
    { title: '对标视频', dataIndex: 'name', key: 'name' },
    { title: '大小', dataIndex: 'size', key: 'size', render: formatBytes },
    {
      title: '操作',
      key: 'actions',
      width: 92,
      render: (_: unknown, item: HypitReference) => (
        <Popconfirm
          title="删除这个对标视频？"
          okText="删除"
          cancelText="取消"
          onConfirm={() => deleteMutation.mutate(item.name)}
        >
          <Button danger type="text" icon={<DeleteOutlined />} aria-label={`删除 ${item.name}`} />
        </Popconfirm>
      ),
    },
  ]

  const buildColumns = [
    {
      title: '作品名称',
      key: 'title',
      render: (_: unknown, item: HypitBuild) => (
        <Input.Search
          aria-label={`编辑作品名称 ${item.id}`}
          defaultValue={item.title ?? ''}
          placeholder="未命名作品"
          enterButton={<SaveOutlined />}
          onSearch={(title) => {
            if (title.trim()) titleMutation.mutate({ buildId: item.id, title: title.trim() })
          }}
        />
      ),
    },
    { title: '状态', dataIndex: 'outcome', key: 'outcome', width: 100, render: outcomeTag },
    {
      title: '生成时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (value: string | null) => value ? new Date(value).toLocaleString() : '—',
    },
    {
      title: '操作',
      key: 'actions',
      width: 110,
      render: (_: unknown, item: HypitBuild) => {
        const output = item.targets[0]
        return output && item.outcome === 'complete' ? (
          <Button type="link" icon={<PlayCircleOutlined />} loading={exportingBuildId === item.id} onClick={() => void openBuild(item)}>
            打开成片
          </Button>
        ) : <Typography.Text type="secondary">—</Typography.Text>
      },
    },
  ]

  const assetUpload = (kind: HypitInput['kind'], accept: string, label: string, icon: ReactNode) => (
    <Card size="small" title={<Flex align="center" gap={8}>{icon}{label}</Flex>} style={{ flex: '1 1 240px' }}>
      <Upload
        accept={accept}
        multiple
        showUploadList={false}
        beforeUpload={(file) => {
          inputMutation.mutate({ kind, file })
          return false
        }}
      >
        <Button icon={<UploadOutlined />}>选择文件</Button>
      </Upload>
      <Typography.Paragraph type="secondary" style={{ margin: '10px 0 0' }}>
        {(inputsQuery.data ?? []).filter((item) => item.kind === kind).map((item) => item.name).join('、') || '未选择；可以留空'}
      </Typography.Paragraph>
    </Card>
  )

  return (
    <Flex vertical gap={20} style={{ minHeight: '100%' }}>
      <PageHeader
        title="Hypit 创作"
        description="导入参考视频，指定替换内容，再交给 Hypit 生成可编辑作品"
        extra={
          <Flex gap={8} align="center">
            <Tag color={status?.running ? 'success' : 'default'}>
              {status?.running ? '运行中' : '未运行'}
            </Tag>
            <Typography.Text type="secondary">v{status?.version ?? '0.1.10'}</Typography.Text>
          </Flex>
        }
      />

      <Alert
        type="info"
        showIcon
        message="Hypit 开源来源"
        description={(
          <span>
            本页面集成的 Hypit 由 Hypit.AI 原作者团队维护，版本 {status?.version ?? '0.1.10'}；
            ClipAtlas 仅负责本地启动和工作区桥接。来源：{' '}
            <a href="https://github.com/hypit-ai/hypit" target="_blank" rel="noreferrer">GitHub hypit-ai/hypit</a>
            {' · '}
            <a href="https://hypit.ai" target="_blank" rel="noreferrer">Hypit.AI</a>
            {' · '}
            <a href="https://github.com/hypit-ai/hypit/blob/main/LICENSE" target="_blank" rel="noreferrer">许可证</a>
          </span>
        )}
      />

      {configQuery.error ? <ErrorBlock error={configQuery.error} title="读取 Hypit 配置失败" /> : null}
      {statusQuery.error ? <ErrorBlock error={statusQuery.error} title="读取 Hypit 状态失败" /> : null}
      {operationError ? <ErrorBlock error={operationError} title="Hypit 操作失败" /> : null}
      {formError ? <Alert showIcon type="error" message={formError.message} /> : null}

      <Steps
        current={status?.running ? 4 : referencesQuery.data?.length ? 2 : 0}
        items={[
          { title: '参考视频' },
          { title: '替换素材' },
          { title: '模仿要求' },
          { title: '模型与费用' },
          { title: '生成与编辑' },
          { title: '导出成片' },
        ]}
      />

      <Divider style={{ margin: 0 }} />
      <section>
        <Typography.Title level={4}>1. 导入对标视频</Typography.Title>
        <Upload.Dragger
          aria-label="导入对标视频"
          accept="video/*,.mkv,.m4v"
          multiple={false}
          showUploadList={false}
          customRequest={({ file, onSuccess, onError }) => {
            uploadMutation.mutate(file as File, {
              onSuccess: (result) => onSuccess?.(result),
              onError: (error) => onError?.(error),
            })
          }}
        >
          <UploadOutlined style={{ fontSize: 24 }} />
          <Typography.Paragraph style={{ margin: '8px 0 0' }}>
            点击选择，或把对标视频拖到这里
          </Typography.Paragraph>
          <Typography.Text type="secondary">支持 MP4、MOV、MKV、WebM、AVI、M4V，单个不超过 2 GB</Typography.Text>
        </Upload.Dragger>
        <Alert
          showIcon
          type="info"
          style={{ marginTop: 12 }}
          message="导入后，在 Studio 源文件中将视频引用为参考素材；可模仿的镜头、风格或运动由当前 Source 和视频模型 API 决定。"
        />
        <Table<HypitReference>
          rowKey="name"
          style={{ marginTop: 12 }}
          size="small"
          pagination={false}
          loading={referencesQuery.isPending}
          dataSource={referencesQuery.data ?? []}
          columns={referenceColumns}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有导入对标视频" /> }}
        />
      </section>

      <Divider style={{ margin: 0 }} />
      <section>
        <Typography.Title level={4}>2. 替换素材</Typography.Title>
        <Flex gap={12} wrap="wrap">
          {assetUpload('people', 'image/*', '人物照片', <PictureOutlined />)}
          {assetUpload('products', 'image/*,video/*', '产品 / Logo', <VideoCameraOutlined />)}
          {assetUpload('audio', 'audio/*', '声音参考', <AudioOutlined />)}
        </Flex>
        <Typography.Text type="secondary">这些素材用于生成新镜头；不上传时仍可使用文字要求和已有参考视频。</Typography.Text>
      </section>

      <Divider style={{ margin: 0 }} />
      <section>
        <Typography.Title level={4}>3. 模仿要求</Typography.Title>
        <Input.TextArea
          aria-label="模仿要求"
          value={brief}
          onChange={(event) => setBrief(event.target.value)}
          autoSize={{ minRows: 4, maxRows: 8 }}
          placeholder="例如：保留原视频的开场节奏和三段式结构，把人物换成我的数字人，把产品换成 ClipAtlas，改成中文口播。"
        />
        <Button type="primary" icon={<SaveOutlined />} loading={briefMutation.isPending} onClick={() => briefMutation.mutate(brief)} style={{ marginTop: 12 }}>
          保存制作要求
        </Button>
        <Flex gap={12} wrap="wrap" style={{ marginTop: 12 }}>
          {['保留开场', '保留镜头节奏', '保留字幕风格', '替换人物', '替换产品', '改写文案'].map((text) => (
            <Button key={text} onClick={() => setBrief((current) => current ? `${current}；${text}` : text)}>{text}</Button>
          ))}
        </Flex>
      </section>

      <Divider style={{ margin: 0 }} />
      <section>
        <Typography.Title level={4}>4. 模型与费用</Typography.Title>
        <Alert
          showIcon
          type="info"
          message="模型服务由 Hypit Runtime 管理；当前页面只保存独立 API 配置，不会把凭据交给 ClipAtlas 的其他模块。"
          action={<Button size="small" icon={<SettingOutlined />} onClick={() => document.getElementById('hypit-model-settings')?.scrollIntoView({ behavior: 'smooth' })}>配置 API</Button>}
        />
        {configQuery.isPending || !config ? (
          <Flex justify="center" style={{ padding: 24 }}><Spin /></Flex>
        ) : (
          <Form id="hypit-model-settings" form={form} layout="vertical" requiredMark={false} style={{ marginTop: 16 }}>
            <Flex gap={16} align="flex-start" wrap="wrap">
              <Form.Item name="connection_mode" label="接入类型" style={{ flex: '1 1 240px' }}>
                <Select onChange={selectConnection} options={[
                  { value: 'official', label: 'Hypit 官方' },
                  { value: 'third_party', label: '第三方 API' },
                ]} />
              </Form.Item>
              {connectionMode === 'third_party' ? (
                <Form.Item name="third_party_provider" label="第三方服务商" style={{ flex: '1 1 240px' }}>
                  <Select onChange={selectThirdParty} options={[
                    { value: 'wavespeed', label: 'WaveSpeed AI' },
                    { value: 'custom', label: '其他 Hypit Provider' },
                  ]} />
                </Form.Item>
              ) : null}
              {connectionMode === 'third_party' && thirdPartyProvider === 'wavespeed' ? (
                <Form.Item name="model" label="视频模型" style={{ flex: '1 1 260px' }}>
                  <Select options={[
                    { value: 'seedance-2', label: 'Seedance 2.0' },
                    { value: 'seedance-2.5', label: 'Seedance 2.5' },
                  ]} />
                </Form.Item>
              ) : null}
              <Form.Item name="api_key" label="API Key" style={{ flex: '2 1 360px' }} extra={config.api_key_configured ? '已配置；留空不会覆盖。' : '例如 sk-...；仅保存到 Hypit 独立凭证存储。'}>
                <Input.Password placeholder="例如 sk-your-api-key" autoComplete="new-password" />
              </Form.Item>
            </Flex>
            {connectionMode === 'third_party' && thirdPartyProvider === 'custom' ? (
              <>
                <Alert
                  showIcon
                  type="warning"
                  style={{ marginBottom: 16 }}
                  message="自定义服务需要先在 Hypit Runtime 安装对应 Provider；不同视频 API 协议不通用。"
                />
                <Flex gap={16} align="flex-start" wrap="wrap">
                  <Form.Item name="provider_package" label="Provider 包" rules={[{ required: true, message: '请填写已安装的 Provider 包' }]} style={{ flex: '1 1 300px' }}>
                    <Input placeholder="例如 @vendor/hypit-provider" />
                  </Form.Item>
                  <Form.Item name="endpoint" label="端点名称" rules={[{ required: true }]} style={{ flex: '1 1 220px' }}>
                    <Input placeholder="例如 custom.default" />
                  </Form.Item>
                  <Form.Item name="base_url" label="API 地址" style={{ flex: '2 1 360px' }}>
                    <Input placeholder="https://api.example.com/v1" />
                  </Form.Item>
                </Flex>
                <Form.Item name="provider_config_json" label="Provider 配置（可选 JSON）">
                  <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} placeholder='{"model":"video-model-id"}' />
                </Form.Item>
              </>
            ) : null}
            <Space wrap>
              <Button type="primary" loading={saveMutation.isPending} onClick={() => void save()}>保存模型服务</Button>
              <Button loading={connectionMutation.isPending} onClick={() => void testConnection()}>测试连接</Button>
              {config.api_key_configured ? <Form.Item name="clear_api_key" valuePropName="checked" noStyle><Checkbox>清除已保存的 API Key</Checkbox></Form.Item> : null}
            </Space>
            {connectionNotice ? (
              <Alert
                showIcon
                style={{ marginTop: 12 }}
                type={connectionNotice.ok ? 'success' : 'error'}
                message={connectionNotice.message}
              />
            ) : null}
          </Form>
        )}
        <Radio.Group
          style={{ marginTop: 12 }}
          value={voiceStrategy}
          onChange={(event) => setVoiceStrategy(event.target.value)}
          options={[
            { value: 'original', label: '使用原视频口播（默认）' },
            { value: 'generated', label: '使用生成语音' },
          ]}
        />
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
          当前选择：{voiceStrategy === 'original' ? '优先复用参考视频的口播节奏和声音来源' : '由所选 Provider 生成新语音'}。实际生成仍以 Run Source 和 Provider 能力为准。
        </Typography.Paragraph>
      </section>

      <Divider style={{ margin: 0 }} />
      <section>
        <Typography.Title level={4}>5. 生成与编辑</Typography.Title>
        <Space wrap>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            disabled={status?.running}
            loading={startMutation.isPending}
            onClick={() => startMutation.mutate()}
          >
            启动 Studio
          </Button>
          <Button
            disabled={!status?.running}
            loading={stopMutation.isPending}
            onClick={() => stopMutation.mutate()}
          >
            停止 Studio
          </Button>
        </Space>
        {status?.running && status.url ? (
          <iframe
            title="Hypit Studio"
            src={status.url}
            style={{ width: '100%', minHeight: 720, marginTop: 12, border: '1px solid #d9d9d9' }}
          />
        ) : null}
      </section>

      <Divider style={{ margin: 0 }} />
      <section>
        <Flex justify="space-between" align="center" wrap="wrap" gap={12}>
          <Typography.Title level={4} style={{ margin: 0 }}>6. 导出成片</Typography.Title>
          <Button icon={<ReloadOutlined />} onClick={() => void buildsQuery.refetch()} loading={buildsQuery.isFetching}>
            刷新
          </Button>
        </Flex>
        <Flex gap={8} wrap="wrap" style={{ marginTop: 12 }}>
          <Input
            aria-label="新作品名称"
            placeholder="例如：秋季新品对标短片"
            value={buildTitle}
            maxLength={200}
            onChange={(event) => setBuildTitle(event.target.value)}
            style={{ flex: '1 1 320px' }}
          />
          <Button type="primary" loading={buildMutation.isPending} onClick={() => buildMutation.mutate()}>
            生成作品
          </Button>
        </Flex>
        {buildsQuery.error ? <ErrorBlock error={buildsQuery.error} title="读取 Hypit 作品失败" /> : null}
        <Table<HypitBuild>
          rowKey="id"
          style={{ marginTop: 12 }}
          loading={buildsQuery.isFetching}
          dataSource={buildsQuery.data ?? []}
          columns={buildColumns}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有生成作品" /> }}
        />
        <Typography.Text type="secondary">
          已完成作品由 Hypit 保留执行记录；可改名和导出。参考视频可在上方删除。
        </Typography.Text>
      </section>
    </Flex>
  )
}
