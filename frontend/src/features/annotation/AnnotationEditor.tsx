import { useEffect } from 'react'
import { Button, Drawer, Flex, Form, Input, InputNumber, Select, Switch } from 'antd'

import type {
  SemanticAnnotation,
  UpdateAnnotationInput,
} from '../../api/library'

export type AnnotationEditorValues = {
  description: string
  characters: string[]
  actions: string[]
  scene: string[]
  emotions: string[]
  objects: string[]
  ocr: string[]
  shot_type: string | null
  camera_motion: string | null
  confidence: number | null
  locked: boolean
}

type AnnotationEditorProps = {
  open: boolean
  annotation: SemanticAnnotation | null
  submitting?: boolean
  onCancel: () => void
  onSubmit: (input: UpdateAnnotationInput) => Promise<void> | void
}

export function toAnnotationUpdateInput(values: AnnotationEditorValues): UpdateAnnotationInput {
  return {
    description: values.description,
    characters: values.characters,
    actions: values.actions,
    scene: values.scene,
    emotions: values.emotions,
    objects: values.objects,
    ocr: values.ocr,
    shot_type: values.shot_type,
    camera_motion: values.camera_motion,
    confidence: values.confidence,
    locked: values.locked,
  }
}

function annotationToFormValues(annotation: SemanticAnnotation): AnnotationEditorValues {
  return {
    description: annotation.description,
    characters: annotation.characters,
    actions: annotation.actions,
    scene: annotation.scene,
    emotions: annotation.emotions,
    objects: annotation.objects,
    ocr: annotation.ocr,
    shot_type: annotation.shot_type,
    camera_motion: annotation.camera_motion,
    confidence: annotation.confidence,
    locked: annotation.locked,
  }
}

export function AnnotationEditor({
  open,
  annotation,
  submitting = false,
  onCancel,
  onSubmit,
}: AnnotationEditorProps) {
  const [form] = Form.useForm<AnnotationEditorValues>()

  useEffect(() => {
    if (!open) return
    if (annotation) {
      form.setFieldsValue(annotationToFormValues(annotation))
    } else {
      form.resetFields()
    }
  }, [annotation, form, open])

  async function handleFinish(values: AnnotationEditorValues) {
    await onSubmit(toAnnotationUpdateInput(values))
  }

  return (
    <Drawer
      open={open}
      title="修正片段标注"
      width={640}
      onClose={onCancel}
      destroyOnHidden
    >
      <Form<AnnotationEditorValues>
        form={form}
        layout="vertical"
        onFinish={(values) => void handleFinish(values)}
      >
        <Form.Item
          name="description"
          label="画面描述"
          rules={[{ required: true, message: '请输入画面描述' }]}
        >
          <Input.TextArea rows={4} />
        </Form.Item>

        <Form.Item name="characters" label="人物">
          <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车添加" />
        </Form.Item>
        <Form.Item name="actions" label="动作">
          <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车添加" />
        </Form.Item>
        <Form.Item name="scene" label="场景">
          <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车添加" />
        </Form.Item>
        <Form.Item name="emotions" label="情绪">
          <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车添加" />
        </Form.Item>
        <Form.Item name="objects" label="物体">
          <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车添加" />
        </Form.Item>
        <Form.Item name="ocr" label="画面文字 / OCR">
          <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车添加" />
        </Form.Item>

        <Flex gap={12} wrap>
          <Form.Item name="shot_type" label="镜头类型" style={{ flex: '1 1 220px' }}>
            <Input allowClear />
          </Form.Item>
          <Form.Item name="camera_motion" label="运镜" style={{ flex: '1 1 220px' }}>
            <Input allowClear />
          </Form.Item>
          <Form.Item name="confidence" label="置信度" style={{ flex: '1 1 160px' }}>
            <InputNumber min={0} max={1} step={0.01} style={{ width: '100%' }} />
          </Form.Item>
        </Flex>

        <Form.Item name="locked" label="锁定人工标注" valuePropName="checked">
          <Switch checkedChildren="已锁定" unCheckedChildren="未锁定" />
        </Form.Item>

        <Flex justify="flex-end" gap={8}>
          <Button onClick={onCancel}>取消</Button>
          <Button type="primary" htmlType="submit" loading={submitting}>
            保存人工修正
          </Button>
        </Flex>
      </Form>
    </Drawer>
  )
}
