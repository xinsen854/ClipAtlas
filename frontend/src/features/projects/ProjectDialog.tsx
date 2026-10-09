import { useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Form, Input, Modal, message } from 'antd'
import { useNavigate } from 'react-router-dom'

import {
  createProject,
  updateProject,
  type Project,
} from '../../api/projects'

type ProjectFormValues = {
  name: string
  description?: string
}

type ProjectDialogProps = {
  open: boolean
  project?: Project | null
  onClose: () => void
  onSaved: (project: Project) => void
}

export function ProjectDialog({ open, project, onClose, onSaved }: ProjectDialogProps) {
  const navigate = useNavigate()
  const [form] = Form.useForm<ProjectFormValues>()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()

  useEffect(() => {
    if (!open) return
    form.setFieldsValue({
      name: project?.name ?? '',
      description: project?.description ?? '',
    })
  }, [form, open, project])

  const mutation = useMutation({
    mutationFn: async (values: ProjectFormValues) => {
      const description = values.description?.trim() || null
      if (project) {
        return updateProject(project.id, { name: values.name.trim(), description })
      }
      return createProject({ name: values.name.trim(), description })
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      messageApi.success(project ? '项目已更新' : '项目已创建')
      onSaved(saved)
      onClose()
      if (!project) void navigate('/rules')
    },
  })

  async function submit() {
    const values = await form.validateFields()
    mutation.mutate(values)
  }

  return (
    <>
      {contextHolder}
      <Modal
        open={open}
        title={project ? '编辑项目' : '新建项目'}
        okText={project ? '保存' : '创建'}
        cancelText="取消"
        confirmLoading={mutation.isPending}
        onOk={() => void submit()}
        onCancel={onClose}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item
            label="项目名称"
            name="name"
            rules={[
              { required: true, message: '请输入项目名称' },
              { max: 200, message: '项目名称不能超过 200 个字符' },
            ]}
          >
            <Input placeholder="例如：电影解说第 01 期" autoFocus />
          </Form.Item>
          <Form.Item
            label="项目说明"
            name="description"
            rules={[{ max: 2000, message: '项目说明不能超过 2000 个字符' }]}
          >
            <Input.TextArea rows={4} placeholder="可选，用于记录本次创作任务" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
