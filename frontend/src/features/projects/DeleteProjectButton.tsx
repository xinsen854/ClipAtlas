import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App, Alert, Button, Modal, Space, Typography } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import { deleteProject, getProjectDeletionPreview, type Project } from '../../api/projects'
import { ErrorBlock } from '../../components/ErrorBlock'
import { useAppStore } from '../../stores/useAppStore'

export function DeleteProjectButton({ project }: { project: Project }) {
  const [selected, setSelected] = useState<Project | null>(null)
  const client = useQueryClient()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const preview = useQuery({
    queryKey: ['project', selected?.id, 'deletion-preview'],
    queryFn: () => getProjectDeletionPreview(selected!.id), enabled: selected !== null,
  })
  const remove = useMutation({
    mutationFn: deleteProject,
    onSuccess: async (result) => {
      const remaining = (client.getQueryData<Project[]>(['projects']) ?? []).filter(p => p.id !== result.project_id)
      client.setQueryData(['projects'], remaining)
      client.removeQueries({ queryKey: ['project', result.project_id] })
      client.removeQueries({ queryKey: ['narration-batch', result.project_id] })
      client.removeQueries({ queryKey: ['narration'] })
      if (useAppStore.getState().currentProjectId === result.project_id) {
        useAppStore.getState().setCurrentProjectId(remaining[0]?.id ?? null)
        void navigate('/')
      }
      setSelected(null)
      await client.invalidateQueries({ queryKey: ['projects'] })
      if (result.warnings.length) void message.warning(result.warnings.join('；'))
      else void message.success(`已删除项目“${result.name}”及专属文件，共享素材库保留。`)
    },
  })
  return <>
    <Button danger aria-label="删除此项目" icon={<DeleteOutlined />} onClick={() => { remove.reset(); setSelected(project) }}>
      删除此项目
    </Button>
    <Modal open={selected !== null} title={`删除项目“${selected?.name ?? ''}”？`}
      okText="确认删除此项目" okButtonProps={{ danger: true, disabled: !preview.isSuccess }}
      confirmLoading={remove.isPending} cancelButtonProps={{ disabled: remove.isPending }}
      closable={!remove.isPending} maskClosable={!remove.isPending}
      onCancel={() => setSelected(null)} onOk={() => selected && remove.mutate(selected.id)}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Alert type="warning" showIcon message="项目专属内容将被删除"
          description="包括文案、旁白音频、批次记录、规则、粗剪方案及项目内部生成文件。操作前会备份数据库。" />
        <Typography.Paragraph>
          全局素材库、Visual / ASR / OCR 索引与抽帧缓存由所有项目共用，将继续保留。
          原始视频、已导出的剪映草稿和其他项目不受影响。
        </Typography.Paragraph>
        {preview.data ? <>
          <Typography.Text>旁白 {preview.data.narrations} 条 · 粗剪 {preview.data.plans} 个 · 批次 {preview.data.batches} 个</Typography.Text>
          {preview.data.directories.map(path => <Typography.Text key={path} code>{path}</Typography.Text>)}
          {preview.data.warnings.map(warning => <Alert key={warning} type="warning" message={warning} />)}
        </> : null}
        {preview.isPending ? <Typography.Text>正在核对项目文件…</Typography.Text> : null}
        {preview.error ? <ErrorBlock error={preview.error} title="无法确认删除范围" /> : null}
        {remove.error ? <ErrorBlock error={remove.error} title="项目未能删除" /> : null}
      </Space>
    </Modal>
  </>
}
