import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Flex, Input, Modal, Select, Space, Tag, Typography } from 'antd'
import { FolderOpenOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { lanConnectionId } from '../api/lanConnection'

declare global {
  interface Window { pywebview?: { api: { choose_folder: () => Promise<string | null> } } }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || '本地素材操作失败')
  return data
}

type Folder = { root: string | null; count: number; skipped?: number }
export function LocalFolder() {
  const cache = useQueryClient()
  const folder = useQuery({ queryKey: ['local-folder'], queryFn: () => request<Folder>('/lan/folder') })
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function scan(value: string) {
    if (!value.trim()) return
    setBusy(true); setError('')
    try {
      const result = await request<Folder>('/lan/folder', { path: value })
      cache.setQueryData(['local-folder'], result)
      await cache.invalidateQueries({ queryKey: ['local-match'] })
      setPath(value)
    } catch (e) { setError(e instanceof Error ? e.message : '扫描失败') }
    finally { setBusy(false) }
  }
  async function choose() {
    setError('')
    if (!window.pywebview) { setError('请在下方输入本地文件夹路径，再点击扫描。'); return }
    try {
      const selected = await window.pywebview.api.choose_folder()
      if (selected) await scan(selected)
    } catch (e) { setError(e instanceof Error ? e.message : '选择文件夹失败') }
  }
  return <Flex vertical gap={10} style={{ marginTop: 18, borderTop: '1px solid #eee', paddingTop: 18 }}>
    <Flex gap={12} align="center" wrap>
      <Typography.Text strong>我的本地素材</Typography.Text>
      <Button icon={<FolderOpenOutlined />} loading={busy} onClick={() => void choose()}>选择本地素材文件夹</Button>
      <Input aria-label="本地素材文件夹路径" style={{ width: 360 }} value={path || folder.data?.root || ''}
        placeholder="例如 D:\\视频素材（包含子文件夹）" onChange={e => setPath(e.target.value)} />
      <Button loading={busy} onClick={() => void scan(path || folder.data?.root || '')}>扫描 / 刷新</Button>
      {folder.data?.root && <Tag color="green">已收录 {folder.data.count} 个本地视频</Tag>}
    </Flex>
    <Typography.Text type="secondary">选好本机文件夹后，搜索命中会核对本地视频，支持一键定位和本地播放。修改了文件后请刷新。</Typography.Text>
    {!!folder.data?.skipped && <Alert type="warning" message={`有 ${folder.data.skipped} 个文件或目录无法读取，已跳过。`} />}
    {error && <Alert type="error" message={error} />}
  </Flex>
}

type Candidate = { id: string; name: string; path: string; relative: string; verified: boolean }
type Match = { status: string; candidates: Candidate[] }
export function LocalMaterial({ videoId, startMs, endMs }: { videoId: string; startMs: number; endMs: number }) {
  const connection = lanConnectionId()
  const [selected, setSelected] = useState<string>()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const match = useQuery({ queryKey: ['local-match', connection, videoId], enabled: !!connection,
    queryFn: () => request<Match>('/lan/local-match', { connection, video_id: videoId }), retry: false })
  if (!connection) return null
  const candidates = match.data?.candidates || []
  const candidate = candidates.find(c => c.id === selected) || (candidates.length === 1 && candidates[0].verified ? candidates[0] : undefined)
  async function reveal() {
    if (!candidate) return
    setError('')
    try { await request(`/lan/local/${candidate.id}/reveal`, {}) }
    catch (e) { setError(e instanceof Error ? e.message : '无法定位文件') }
  }
  return <Flex vertical gap={8} style={{ padding: 14, borderRadius: 10, background: '#f8f4ef' }}>
    {match.isPending && <Typography.Text type="secondary">正在匹配本地素材…</Typography.Text>}
    {match.error && <Alert type="warning" message={match.error.message} action={<Button onClick={() => void match.refetch()}>重试</Button>} />}
    {match.data?.status === 'no-folder' && <Typography.Text type="secondary">选择“我的本地素材”文件夹后，可直接定位本机视频。</Typography.Text>}
    {match.data?.status === 'missing' && <Typography.Text type="secondary">本地未匹配到对应视频，请确认目录内有原素材副本，再扫描 / 刷新。</Typography.Text>}
    {candidates.length > 0 && <>
      <Space wrap><Tag color={candidate?.verified ? 'green' : 'orange'}>{candidate?.verified ? '已匹配本地素材 · 大小及抽样内容一致' : '请选择并确认本地素材'}</Tag>
        {candidate && <Typography.Text strong>{candidate.name}</Typography.Text>}</Space>
      {(candidates.length > 1 || !candidates[0].verified) && <>
        <Typography.Text type="secondary">{candidates[0].verified ? '发现多个相同副本，请选择要使用的文件。' : '共享端原文件不可读，以下仅为同名候选，请核对后选择。'}</Typography.Text>
        <Select aria-label="选择本地视频" value={candidate?.id} placeholder="选择对应的本地视频"
          options={candidates.map(c => ({ value: c.id, label: c.relative }))} onChange={setSelected} />
      </>}
      {candidate && <><Typography.Text copyable={{ text: candidate.path }}>{candidate.path}</Typography.Text>
        <Space wrap><Button icon={<FolderOpenOutlined />} onClick={() => void reveal()}>一键定位本地文件</Button>
          <Button icon={<PlayCircleOutlined />} onClick={() => { setError(''); setOpen(true) }}>播放本地命中片段</Button></Space></>}
    </>}
    {error && <Alert type="warning" message={error} />}
    <Modal open={open && !!candidate} title={candidate?.name || '本地素材'} footer={null} width={880} destroyOnHidden onCancel={() => setOpen(false)}>
      {open && candidate && <video key={candidate.id} controls autoPlay preload="metadata" style={{ width: '100%', maxHeight: '65vh' }}
        src={`/lan/local/${candidate.id}/media#t=${startMs / 1000},${endMs / 1000}`}
        onLoadedMetadata={e => { e.currentTarget.currentTime = startMs / 1000 }}
        onTimeUpdate={e => { if (e.currentTarget.currentTime >= endMs / 1000) e.currentTarget.pause() }}
        onPlay={e => { if (e.currentTarget.currentTime >= endMs / 1000) e.currentTarget.currentTime = startMs / 1000 }}
        onError={() => setError('本地视频无法播放，可能已移动或编码不受支持；可使用一键定位后用本地播放器打开。')} />}
    </Modal>
  </Flex>
}
