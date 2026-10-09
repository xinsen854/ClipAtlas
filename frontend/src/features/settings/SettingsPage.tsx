import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App as AntdApp, Alert, Button, Flex, Form, Input, Select, Spin, Typography } from 'antd'

import {
  detectBailianModels,
  getSettings,
  testSettingsConnection,
  updateSettings,
  type BailianModelDetectionInput,
  type BailianModelStatus,
  type ProbeSettingsInput,
  type PublicSettings,
  type PublicSettingValue,
  type SettingsPatch,
} from '../../api/settings'
import { ErrorBlock } from '../../components/ErrorBlock'
import { PageHeader } from '../../components/PageHeader'
import { PathPickerInput } from '../../components/PathPickerInput'
import { SecretField } from './SecretField'
import { SettingsSection } from './SettingsSection'
import { CacheLocationCard } from './CacheLocationCard'
import { LogViewerModal } from './LogViewerModal'

const SETTINGS_QUERY_KEY = ['settings'] as const
const ENVIRONMENT_NOTICE = '由环境变量管理；本机配置不会覆盖当前环境变量。'
const DASHSCOPE_SPEECH_ENDPOINT = 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer'
const DASHSCOPE_SPEECH_MODEL = 'cosyvoice-v3.5-flash'
const BAILIAN_MODELS = [
  { id: 'video_embedding', label: '视频向量', model: 'qwen3-vl-embedding' },
  { id: 'video_understanding', label: '视频理解', model: 'qwen3.8-flash' },
  { id: 'ocr', label: 'OCR', model: 'qwen3.5-ocr' },
  { id: 'asr', label: 'ASR', model: 'qwen-audio-3.0-asr-flash' },
  { id: 'media_type', label: '画面类型标注', model: 'qwen3.8-flash' },
  { id: 'director', label: '文案解析', model: 'qwen3.8-flash' },
] as const

type SettingsFormValues = {
  bailian_base_url?: string
  speech_provider?: string
  speech_base_url?: string
  speech_model?: string
  jianying_draft_root?: string
  jianying_install_dir?: string
  jianying_user_data?: string
  jianying_mode?: 'portable' | 'jianying_pro_10_8'
  jianying_executable?: string
}

type SecretName = 'bailian_api_key' | 'speech_api_key'
type ClearFlagName = 'clear_bailian_api_key' | 'clear_speech_api_key'
type SecretState = Record<SecretName, string>
type ClearState = Record<ClearFlagName, boolean>
type ProbeNotice = {
  type: 'success' | 'error' | 'warning'
  message: string
}

const EMPTY_SECRETS: SecretState = {
  bailian_api_key: '',
  speech_api_key: '',
}

const EMPTY_CLEAR_FLAGS: ClearState = {
  clear_bailian_api_key: false,
  clear_speech_api_key: false,
}

const EMPTY_BAILIAN_MODEL_STATUS: Record<string, BailianModelStatus> = Object.fromEntries(
  BAILIAN_MODELS.map(({ id }) => [id, 'undetected' as const]),
)

function stringValue(setting: PublicSettingValue): string {
  return typeof setting.value === 'string' ? setting.value : ''
}

function optionalText(value: string | undefined): string | null {
  const normalized = value?.trim() ?? ''
  return normalized || null
}

function sourceExtra(setting: PublicSettingValue) {
  if (setting.source === 'environment') {
    return <Typography.Text type="warning">{ENVIRONMENT_NOTICE}</Typography.Text>
  }
  return (
    <Typography.Text type="secondary">
      {setting.source === 'file' ? '来源：本机配置' : '来源：默认值'}
    </Typography.Text>
  )
}

function sourceExtraWithHint(setting: PublicSettingValue, hint: string) {
  return (
    <Flex vertical gap={2}>
      {sourceExtra(setting)}
      <Typography.Text type="secondary">{hint}</Typography.Text>
    </Flex>
  )
}

function formValues(settings: PublicSettings): SettingsFormValues {
  const mode = stringValue(settings.jianying_mode)
  return {
    bailian_base_url: stringValue(settings.bailian_base_url),
    speech_provider: stringValue(settings.speech_provider),
    speech_base_url: stringValue(settings.speech_base_url),
    speech_model: stringValue(settings.speech_model),
    jianying_draft_root: stringValue(settings.jianying_draft_root),
    jianying_install_dir: stringValue(settings.jianying_install_dir),
    jianying_user_data: stringValue(settings.jianying_user_data),
    jianying_mode: mode === 'jianying_pro_10_8' ? 'jianying_pro_10_8' : 'portable',
    jianying_executable: stringValue(settings.jianying_executable),
  }
}

function buildPatch(
  values: SettingsFormValues,
  secrets: SecretState,
  clearFlags: ClearState,
): SettingsPatch {
  const patch: SettingsPatch = {
    bailian_base_url: optionalText(values.bailian_base_url),
    speech_provider: 'dashscope',
    speech_base_url: DASHSCOPE_SPEECH_ENDPOINT,
    speech_model: DASHSCOPE_SPEECH_MODEL,
    jianying_draft_root: optionalText(values.jianying_draft_root),
    jianying_install_dir: optionalText(values.jianying_install_dir),
    jianying_user_data: optionalText(values.jianying_user_data),
    jianying_mode: values.jianying_mode ?? null,
    jianying_executable: optionalText(values.jianying_executable),
  }

  const bailianSecret = secrets.bailian_api_key.trim()
  if (bailianSecret) patch.bailian_api_key = bailianSecret
  const speechSecret = secrets.speech_api_key.trim()
  if (speechSecret) patch.speech_api_key = speechSecret

  if (clearFlags.clear_bailian_api_key) patch.clear_bailian_api_key = true
  if (clearFlags.clear_speech_api_key) patch.clear_speech_api_key = true

  return patch
}

function withTransientKey(
  input: Omit<ProbeSettingsInput, 'api_key'>,
  rawKey: string,
): ProbeSettingsInput {
  const apiKey = rawKey.trim()
  return apiKey ? { ...input, api_key: apiKey } : input
}

function bailianDetectionInput(baseUrl: string, rawKey: string): BailianModelDetectionInput {
  const input: BailianModelDetectionInput = { base_url: baseUrl.trim() }
  const apiKey = rawKey.trim()
  return apiKey ? { ...input, api_key: apiKey } : input
}

function modelStatusText(status: BailianModelStatus): string {
  if (status === 'available') return '✅ 可用'
  if (status === 'unavailable') return '❌ 不可用'
  return '未检测'
}

export function SettingsPage() {
  const [form] = Form.useForm<SettingsFormValues>()
  const { message } = AntdApp.useApp()
  const queryClient = useQueryClient()
  const [secrets, setSecrets] = useState<SecretState>(EMPTY_SECRETS)
  const [clearFlags, setClearFlags] = useState<ClearState>(EMPTY_CLEAR_FLAGS)
  const [savedNotice, setSavedNotice] = useState(false)
  const [speechNotice, setSpeechNotice] = useState<ProbeNotice | null>(null)
  const [bailianNotice, setBailianNotice] = useState<ProbeNotice | null>(null)
  const [bailianModels, setBailianModels] = useState<Record<string, BailianModelStatus>>(
    EMPTY_BAILIAN_MODEL_STATUS,
  )
  const [logsOpen, setLogsOpen] = useState(false)

  const settingsQuery = useQuery({
    queryKey: SETTINGS_QUERY_KEY,
    queryFn: getSettings,
  })

  useEffect(() => {
    if (!settingsQuery.data) return
    form.setFieldsValue(formValues(settingsQuery.data))
    setSecrets(EMPTY_SECRETS)
    setClearFlags(EMPTY_CLEAR_FLAGS)
    setSpeechNotice(null)
    setBailianNotice(null)
    setBailianModels(EMPTY_BAILIAN_MODEL_STATUS)
  }, [form, settingsQuery.data])

  const saveMutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: (response) => {
      queryClient.setQueryData(SETTINGS_QUERY_KEY, response.settings)
      setSecrets(EMPTY_SECRETS)
      setClearFlags(EMPTY_CLEAR_FLAGS)
      setSavedNotice(true)
      void message.success('设置已保存')
    },
  })

  const connectionMutation = useMutation({
    mutationFn: testSettingsConnection,
    onSuccess: (response) => {
      setSpeechNotice({
        type: response.ok ? 'success' : 'error',
        message: response.message,
      })
    },
    onError: (error) => {
      setSpeechNotice({
        type: 'error',
        message: error instanceof Error ? error.message : '连接测试失败。',
      })
    },
  })

  const bailianModelsMutation = useMutation({
    mutationFn: detectBailianModels,
    onSuccess: (response) => {
      setBailianModels(response.models)
      setBailianNotice({
        type: response.ok ? 'success' : 'error',
        message: response.message,
      })
    },
    onError: (error) => {
      setBailianModels(EMPTY_BAILIAN_MODEL_STATUS)
      setBailianNotice({
        type: 'error',
        message: error instanceof Error ? error.message : '检查百炼模型失败。',
      })
    },
  })

  function changeSecret(
    secretName: SecretName,
    clearFlagName: ClearFlagName,
    value: string,
  ) {
    setSecrets((current) => ({ ...current, [secretName]: value }))
    if (value.trim()) {
      setClearFlags((current) => ({ ...current, [clearFlagName]: false }))
    }
  }

  function clearSecret(secretName: SecretName, clearFlagName: ClearFlagName) {
    setSecrets((current) => ({ ...current, [secretName]: '' }))
    setClearFlags((current) => ({ ...current, [clearFlagName]: true }))
  }

  function testSpeechConnection() {
    const values = form.getFieldsValue()
    setSpeechNotice(null)
    connectionMutation.mutate(
      withTransientKey(
        {
          service: 'speech',
          provider: 'dashscope',
          base_url: DASHSCOPE_SPEECH_ENDPOINT,
          model: DASHSCOPE_SPEECH_MODEL,
        },
        secrets.speech_api_key,
      ),
    )
  }

  function checkBailianModels() {
    const baseUrl = form.getFieldValue('bailian_base_url') ?? ''
    setBailianNotice(null)
    setBailianModels(EMPTY_BAILIAN_MODEL_STATUS)
    bailianModelsMutation.mutate(bailianDetectionInput(baseUrl, secrets.bailian_api_key))
  }

  async function save() {
    const values = await form.validateFields()
    setSavedNotice(false)
    saveMutation.mutate(buildPatch(values, secrets, clearFlags))
  }

  const settings = settingsQuery.data

  return (
    <Flex vertical gap={20}>
      <PageHeader
        title="设置"
        description="配置阿里云百炼、语音和剪映参数。保存后需重启 ClipAtlas 才会生效。"
        extra={
          <Button onClick={() => setLogsOpen(true)}>运行日志</Button>
        }
      />
      <LogViewerModal open={logsOpen} onClose={() => setLogsOpen(false)} />
      <CacheLocationCard />

      {settingsQuery.error ? <ErrorBlock error={settingsQuery.error} title="读取设置失败" /> : null}
      {saveMutation.error ? <ErrorBlock error={saveMutation.error} title="保存设置失败" /> : null}
      {savedNotice ? (
        <Alert type="success" showIcon message="设置已保存。重启 ClipAtlas 后生效。" />
      ) : null}

      {settingsQuery.isPending || !settings ? (
        <Flex justify="center" style={{ padding: 48 }}>
          <Spin tip="读取设置中" />
        </Flex>
      ) : (
        <Form form={form} layout="vertical" requiredMark={false}>
          <Flex vertical gap={20}>
            <SettingsSection
              tone="bailian"
              title="阿里云百炼"
              description="非 TTS AI 能力统一使用这一组 API Key 与 Workspace / Base URL。"
            >
              <SecretField
                label="百炼 API Key"
                configured={settings.bailian_api_key_configured}
                source={settings.bailian_api_key_source}
                value={secrets.bailian_api_key}
                clearPending={clearFlags.clear_bailian_api_key}
                onChange={(value) =>
                  changeSecret('bailian_api_key', 'clear_bailian_api_key', value)
                }
                onClear={() => clearSecret('bailian_api_key', 'clear_bailian_api_key')}
              />
              <Form.Item
                name="bailian_base_url"
                label="Workspace / Base URL"
                extra={sourceExtraWithHint(
                  settings.bailian_base_url,
                  '填写 aliyuncs.com 的 Workspace 地址；软件会自动派生 compatible-mode/v1 与 api/v1。',
                )}
              >
                <Input />
              </Form.Item>
              <Button loading={bailianModelsMutation.isPending} onClick={checkBailianModels}>
                检查模型
              </Button>
              {bailianNotice ? (
                <Alert showIcon type={bailianNotice.type} message={bailianNotice.message} />
              ) : null}
              <Flex vertical gap={8}>
                {BAILIAN_MODELS.map(({ id, label, model }) => (
                  <Flex key={id} justify="space-between" gap={16} wrap>
                    <Typography.Text>
                      {label} · {model}
                    </Typography.Text>
                    <Typography.Text>{modelStatusText(bailianModels[id] ?? 'undetected')}</Typography.Text>
                  </Flex>
                ))}
              </Flex>
            </SettingsSection>

            <SettingsSection
              tone="speech"
              title="语音服务"
              description="用于 AI 旁白生成；具体声音参数仍在文案与旁白页管理。"
            >
              <SecretField
                label="语音 API Key"
                configured={settings.speech_api_key_configured}
                source={settings.speech_api_key_source}
                value={secrets.speech_api_key}
                clearPending={clearFlags.clear_speech_api_key}
                onChange={(value) => changeSecret('speech_api_key', 'clear_speech_api_key', value)}
                onClear={() => clearSecret('speech_api_key', 'clear_speech_api_key')}
              />
              <Typography.Text type="secondary">
                已内置百炼 CosyVoice（{DASHSCOPE_SPEECH_MODEL}），连接地址由系统管理。
              </Typography.Text>
              <Flex gap={8} wrap>
                <Button loading={connectionMutation.isPending} onClick={testSpeechConnection}>
                  测试连接
                </Button>
              </Flex>
              {speechNotice ? (
                <Alert showIcon type={speechNotice.type} message={speechNotice.message} />
              ) : null}
            </SettingsSection>

            <SettingsSection
              tone="jianying"
              title="剪映"
              description="配置草稿目录和本机剪映程序位置；不接受任意命令。"
            >
              <Form.Item
                name="jianying_draft_root"
                label="草稿根目录"
                extra={sourceExtra(settings.jianying_draft_root)}
              >
                <PathPickerInput placeholder="例如 E:/JianyingPro Drafts" />
              </Form.Item>
              <Form.Item
                name="jianying_install_dir"
                label="安装目录"
                extra={sourceExtraWithHint(
                  settings.jianying_install_dir,
                  '只填写剪映安装文件夹，不要填写 exe 或启动参数。',
                )}
              >
                <PathPickerInput placeholder="例如 D:/jianyingPro" />
              </Form.Item>
              <Form.Item
                name="jianying_user_data"
                label="用户数据目录"
                extra={sourceExtraWithHint(
                  settings.jianying_user_data,
                  'Portable 草稿可留空；剪映专业版 10.8 接线时再填写。',
                )}
              >
                <PathPickerInput />
              </Form.Item>
              <Form.Item
                name="jianying_mode"
                label="草稿模式"
                extra={sourceExtra(settings.jianying_mode)}
              >
                <Select
                  options={[
                    { value: 'portable', label: 'Portable 草稿' },
                    { value: 'jianying_pro_10_8', label: '剪映专业版 10.8' },
                  ]}
                />
              </Form.Item>
              <Form.Item
                name="jianying_executable"
                label="剪映可执行文件"
                extra={sourceExtraWithHint(
                  settings.jianying_executable,
                  '只填写剪映 .exe 文件路径，不要附加 --src1 等启动参数。',
                )}
              >
                <PathPickerInput picker="file" placeholder="例如 D:/jianyingPro/JianyingPro.exe" />
              </Form.Item>
            </SettingsSection>

            <Flex justify="flex-end">
              <Button type="primary" loading={saveMutation.isPending} onClick={() => void save()}>
                保存设置
              </Button>
            </Flex>
          </Flex>
        </Form>
      )}
    </Flex>
  )
}
