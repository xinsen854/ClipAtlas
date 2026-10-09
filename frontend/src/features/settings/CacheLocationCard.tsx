import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Flex, Modal, Typography } from 'antd'
import { getCacheLocation, moveCacheLocation } from '../../api/library'
import { PathPickerInput } from '../../components/PathPickerInput'
import { ErrorBlock } from '../../components/ErrorBlock'

export function CacheLocationCard() {
  const [draft, setDraft] = useState<string | null>(null)
  const [confirmPath, setConfirmPath] = useState<string | null>(null)
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['library', 'cache-location'], queryFn: getCacheLocation })
  const move = useMutation({ mutationFn: moveCacheLocation, onSuccess: async () => {
    setConfirmPath(null)
    await client.invalidateQueries({ queryKey: ['library'] })
    await client.invalidateQueries({ queryKey: ['settings'] })
  } })
  const value = draft ?? query.data?.path ?? ''
  const restart = query.data?.restart_required || move.data?.restart_required
  return <Card title="素材缓存位置">
    <Flex vertical gap={12}>
      <Typography.Text>缓存保存在本机，与全局素材库共用，关闭软件后仍会保留。</Typography.Text>
      <Typography.Text type="secondary">更换目录会迁移已有缓存并更新路径引用，解析结果保留。请选择专用空目录，完成后需要重启 ClipAtlas。</Typography.Text>
      <PathPickerInput aria-label="素材缓存目录" value={value} onChange={setDraft}
        placeholder="例如 B:/ClipAtlasCache" disabled={move.isPending || restart || query.data?.environment_managed} />
      <Button disabled={!query.data || !value.trim() || value === query.data.path || restart || query.data.environment_managed}
        loading={move.isPending} onClick={() => { move.reset(); setConfirmPath(value.trim()) }}>
        迁移到此目录
      </Button>
      {query.data?.environment_managed ? <Alert type="info" message="当前目录由环境变量管理，需先移除该变量才能在这里更改。" /> : null}
      {restart ? <Alert type="success" showIcon message="缓存目录已迁移，请重启 ClipAtlas 后继续操作。" /> : null}
      {move.data?.warning ? <Alert type="warning" message={move.data.warning} /> : null}
      {query.error ? <ErrorBlock error={query.error} title="读取缓存位置失败" /> : null}
      {move.error ? <ErrorBlock error={move.error} title="缓存迁移失败，原缓存保留" /> : null}
    </Flex>
    <Modal open={confirmPath !== null} title="迁移素材缓存目录" okText="确认迁移"
      confirmLoading={move.isPending} closable={!move.isPending} maskClosable={!move.isPending}
      cancelButtonProps={{ disabled: move.isPending }} onCancel={() => setConfirmPath(null)}
      onOk={() => confirmPath && move.mutate(confirmPath)}>
      <Typography.Paragraph>从：{query.data?.path}</Typography.Paragraph>
      <Typography.Paragraph>到：{confirmPath}</Typography.Paragraph>
      <Typography.Paragraph>会先备份数据库，再复制并校验缓存，成功后更新引用并移除旧缓存。不会移动原始视频或重新解析素材。</Typography.Paragraph>
      <Alert type="warning" showIcon message="迁移期间请勿关闭软件；完成后需重启。" />
    </Modal>
  </Card>
}
