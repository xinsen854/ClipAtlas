import { useEffect } from 'react'
import {
  Button,
  Checkbox,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
} from 'antd'

import type {
  AgeStyle,
  CreateSpeechProfileInput,
  SpeechProviderDescriptor,
  VoiceDescriptor,
  VoiceGender,
} from '../../api/speech'

export type SpeechProfileFormValues = {
  provider: string
  voice_id: string
  gender_constraint: VoiceGender | null
  age_style_constraint: AgeStyle | null
  language: string | null
  accent: string | null
  speed: number | null
  pitch: number | null
  volume: number | null
  emotion: string | null
  style: string | null
  instruction: string | null
  locked: boolean
}

type SpeechProfileFormProps = {
  projectId: string
  providers: SpeechProviderDescriptor[]
  voices: VoiceDescriptor[]
  submitting?: boolean
  onProviderChange: (provider: string) => void
  onSubmit: (input: CreateSpeechProfileInput) => Promise<void> | void
}

const genderOptions: Array<{ value: VoiceGender; label: string }> = [
  { value: 'unrestricted', label: '不限' },
  { value: 'female', label: '女声' },
  { value: 'male', label: '男声' },
  { value: 'neutral', label: '中性' },
  { value: 'unknown', label: '未知' },
]

const ageOptions: Array<{ value: AgeStyle; label: string }> = [
  { value: 'unrestricted', label: '不限' },
  { value: 'youth', label: '少年' },
  { value: 'young', label: '青年' },
  { value: 'mature', label: '成熟' },
  { value: 'elderly', label: '年长' },
  { value: 'unknown', label: '未知' },
]

export function toSpeechProfileInput(
  projectId: string,
  values: SpeechProfileFormValues,
): CreateSpeechProfileInput {
  return {
    project_id: projectId,
    provider: values.provider,
    voice_id: values.voice_id,
    gender_constraint: values.gender_constraint,
    age_style_constraint: values.age_style_constraint,
    language: values.language,
    accent: values.accent,
    speed: values.speed,
    pitch: values.pitch,
    volume: values.volume,
    emotion: values.emotion,
    style: values.style,
    instruction: values.instruction,
    locked: values.locked,
  }
}

export function SpeechProfileForm({
  projectId,
  providers,
  voices,
  submitting = false,
  onProviderChange,
  onSubmit,
}: SpeechProfileFormProps) {
  const [form] = Form.useForm<SpeechProfileFormValues>()
  const provider = Form.useWatch('provider', form)

  useEffect(() => {
    if (!provider && providers.length) {
      const first = providers[0].name
      form.setFieldValue('provider', first)
      onProviderChange(first)
    }
  }, [form, onProviderChange, provider, providers])

  async function handleFinish(values: SpeechProfileFormValues) {
    await onSubmit(toSpeechProfileInput(projectId, values))
  }

  return (
    <Form<SpeechProfileFormValues>
      form={form}
      layout="vertical"
      initialValues={{
        gender_constraint: 'unrestricted',
        age_style_constraint: 'unrestricted',
        language: 'zh',
        accent: null,
        speed: 1,
        pitch: 0,
        volume: 1,
        emotion: null,
        style: null,
        instruction: null,
        locked: false,
      }}
      onFinish={(values) => void handleFinish(values)}
    >
      <Row gutter={12}>
        <Col xs={24} md={12}>
          <Form.Item name="provider" label="配音服务" rules={[{ required: true, message: '请选择配音服务' }]}>
            <Select
              options={providers.map((item) => ({ value: item.name, label: `${item.name} · ${item.model}` }))}
              onChange={(value) => {
                form.setFieldValue('voice_id', '')
                onProviderChange(value)
              }}
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="预设音色">
            <Select
              allowClear
              showSearch
              placeholder="可选；也可直接填写自定义音色 ID"
              optionFilterProp="label"
              options={voices.map((voice) => ({
                value: voice.voice_id,
                label: `${voice.display_name} · ${voice.voice_id}`,
              }))}
              onChange={(value) => form.setFieldValue('voice_id', value ?? '')}
            />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item name="voice_id" label="音色 ID" rules={[{ required: true, message: '请输入或选择音色 ID' }]}>
        <Input placeholder="支持预设音色或自定义 voice_id" autoComplete="off" />
      </Form.Item>

      <Row gutter={12}>
        <Col xs={24} md={8}>
          <Form.Item name="gender_constraint" label="性别偏好">
            <Select options={genderOptions} />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="age_style_constraint" label="年龄风格">
            <Select options={ageOptions} />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="language" label="语言">
            <Input allowClear placeholder="例如 zh" />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={12}>
        <Col xs={24} md={8}>
          <Form.Item name="speed" label="语速">
            <InputNumber min={0.25} max={4} step={0.05} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="pitch" label="音高">
            <InputNumber step={0.1} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="volume" label="音量">
            <InputNumber min={0} step={0.05} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={12}>
        <Col xs={24} md={8}>
          <Form.Item name="emotion" label="情绪">
            <Input allowClear placeholder="例如 温暖 / 克制 / 兴奋" />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="style" label="表达风格">
            <Input allowClear placeholder="例如 自然 / 纪录片 / 广告" />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="accent" label="口音">
            <Input allowClear placeholder="例如 普通话" />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item name="instruction" label="高级指令">
        <Input.TextArea rows={2} allowClear placeholder="可选：进一步描述语气、停顿或表达要求" />
      </Form.Item>

      <Form.Item name="locked" valuePropName="checked">
        <Checkbox>锁定此语音配置</Checkbox>
      </Form.Item>

      <Button type="primary" htmlType="submit" loading={submitting}>
        保存语音配置
      </Button>
    </Form>
  )
}
