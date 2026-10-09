import { Checkbox, Form, Modal } from 'antd'

import type { AddLibraryRootInput } from '../../api/library'
import { PathPickerInput } from '../../components/PathPickerInput'

type LibraryRootDialogProps = {
  open: boolean
  submitting?: boolean
  onCancel: () => void
  onSubmit: (input: AddLibraryRootInput) => Promise<void> | void
}

export type LibraryRootFormValues = {
  path: string
  recursive: boolean
}

export function toLibraryRootInput(values: LibraryRootFormValues): AddLibraryRootInput {
  return { path: values.path, recursive: values.recursive }
}

export function LibraryRootDialog({
  open,
  submitting = false,
  onCancel,
  onSubmit,
}: LibraryRootDialogProps) {
  const [form] = Form.useForm<LibraryRootFormValues>()

  async function handleOk() {
    const values = await form.validateFields()
    await onSubmit(toLibraryRootInput(values))
    form.resetFields()
  }

  function handleCancel() {
    form.resetFields()
    onCancel()
  }

  return (
    <Modal
      open={open}
      title="添加素材目录"
      okText="添加"
      cancelText="取消"
      okButtonProps={{ 'aria-label': '添加' }}
      confirmLoading={submitting}
      onOk={handleOk}
      onCancel={handleCancel}
      destroyOnHidden
    >
      <Form<LibraryRootFormValues>
        form={form}
        layout="vertical"
        initialValues={{ path: '', recursive: true }}
        preserve={false}
      >
        <Form.Item
          name="path"
          label="本地目录"
          rules={[{ required: true, message: '请输入本地素材目录' }]}
        >
          <PathPickerInput placeholder="例如 D:/视频素材" />
        </Form.Item>
        <Form.Item name="recursive" valuePropName="checked">
          <Checkbox>包含子目录</Checkbox>
        </Form.Item>
      </Form>
    </Modal>
  )
}
