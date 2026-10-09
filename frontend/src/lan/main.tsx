import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Alert, AutoComplete, Button, Card, ConfigProvider, Empty, Flex, Select, Space, Tag, Typography } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { DesktopOutlined, ReloadOutlined } from '@ant-design/icons'
import { theme } from '../app/theme'
import { SearchPage } from '../features/search/SearchPage'
import { useAppStore } from '../stores/useAppStore'
import { setLanPrefix } from '../api/lanConnection'
import type { Project } from '../api/projects'
import { LocalFolder } from './LocalMaterial'

type Host = { name: string; url: string }
type Connection = Host & { prefix: string }
const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } })

async function local<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, signal: AbortSignal.timeout(12000) })
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail || '无法连接素材库')
  return body
}

export function LanApp() {
  const [address, setAddress] = useState('')
  const [hosts, setHosts] = useState<Host[]>([])
  const [connection, setConnection] = useState<Connection | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState('')
  const [online, setOnline] = useState(true)
  const attempt = useRef(0)
  const setProject = useAppStore(s => s.setCurrentProjectId)

  async function scan() {
    setScanning(true)
    try {
      const data = await local<{ discovered: Host[]; history: Host[] }>('/lan/hosts')
      setHosts([...new Map([...data.discovered, ...data.history].map(h => [h.url, h])).values()])
    } catch (e) { setError(e instanceof Error ? e.message : '发现电脑失败') }
    finally { setScanning(false) }
  }
  useEffect(() => { void scan() }, [])
  useEffect(() => {
    if (!connection) return
    let active = true
    const timer = window.setInterval(() => {
      void local<{ status: string }>(connection.prefix + '/health').then(
        data => { if (active) setOnline(data.status === 'ok') },
        () => { if (active) setOnline(false) },
      )
    }, 10000)
    return () => { active = false; window.clearInterval(timer) }
  }, [connection])

  async function connect(value: string) {
    if (!value.trim()) return
    const ticket = ++attempt.current
    setAddress(value); setBusy(true); setError(''); setConnection(null); setProjects([]); setSelectedProjectIds([])
    setProject(null); setLanPrefix(''); cache.removeQueries({ queryKey: ['local-match'] })
    try {
      const next = await local<Connection>('/lan/connect', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: value }),
      })
      const list = await local<Project[]>(next.prefix + '/api/v1/projects')
      if (ticket !== attempt.current) return
      setLanPrefix(next.prefix); setProjects(list); setProject(list[0]?.id ?? null)
      setSelectedProjectIds(list[0] ? [list[0].id] : [])
      setConnection(next); setOnline(true)
      setHosts(old => [next, ...old.filter(h => h.url !== next.url)])
    } catch (e) {
      if (ticket === attempt.current) setError(e instanceof Error ? e.message : '连接失败')
    } finally { if (ticket === attempt.current) setBusy(false) }
  }

  return <Flex vertical gap={24} style={{ maxWidth: 1440, margin: 'auto', padding: 32 }}>
    <Flex justify="space-between" align="center" wrap gap={12}>
      <Space><DesktopOutlined style={{ fontSize: 28, color: '#d97706' }} />
        <div><Typography.Title level={3} style={{ margin: 0 }}>ClipAtlas 素材搜索</Typography.Title>
          <Typography.Text type="secondary">局域网版 · 共享标注素材库</Typography.Text></div></Space>
      <Tag color={connection && online ? 'green' : 'default'}>{connection ? (online ? '已连接 · ' + connection.name : '连接中断') : '尚未连接'}</Tag>
    </Flex>
    <Card variant="borderless">
      <Flex gap={16} align="center" wrap>
        <Typography.Text strong>共享电脑</Typography.Text>
        <AutoComplete aria-label="共享电脑" style={{ width: 390, maxWidth: '100%' }} value={address}
          options={hosts.map(h => ({ value: h.url, label: `\\\\${h.name}  ·  ${h.url.replace('http://', '')}` }))}
          placeholder="选择电脑，或输入 \\\\电脑名 / 局域网 IP" onChange={setAddress}
          onSelect={value => void connect(value)}
          onKeyDown={e => { if (e.key === 'Enter') void connect(address) }}
          notFoundContent={scanning ? '正在发现共享电脑…' : '未发现共享端，可输入电脑名或 IP 连接'} />
        <Button type="primary" loading={busy} disabled={!address.trim()} onClick={() => void connect(address)}>连接素材库</Button>
        <Button icon={<ReloadOutlined />} loading={scanning} onClick={() => void scan()}>发现电脑</Button>
        {connection && <><Typography.Text strong>项目（可多选）</Typography.Text>
          <Select mode="multiple" aria-label="项目（可多选）" style={{ minWidth: 280, maxWidth: 520 }}
            value={selectedProjectIds} maxTagCount="responsive" placeholder="选择一个或多个项目"
            options={projects.map(p => ({ value: p.id, label: p.name }))}
            onChange={(ids) => { setSelectedProjectIds(ids); setProject(ids[0] ?? null) }} />
          <Button size="small" onClick={() => {
            const ids = selectedProjectIds.length === projects.length ? [] : projects.map(p => p.id)
            setSelectedProjectIds(ids); setProject(ids[0] ?? null)
          }}>{selectedProjectIds.length === projects.length ? '取消全选' : '全选'}</Button>
          <Tag color={selectedProjectIds.length ? 'blue' : 'orange'}>
            已选 {selectedProjectIds.length} / {projects.length}
          </Tag></>}
      </Flex>
      <Typography.Paragraph type="secondary" style={{ margin: '16px 0 0' }}>
        在存放标注数据的电脑上打开「素材库共享端」即可，原 ClipAtlas 不需要运行。连接成功的电脑会保留在下拉列表。
      </Typography.Paragraph>
      <LocalFolder />
    </Card>
    {error && <Alert type="error" showIcon message="连接失败" description={error} />}
    {connection && !online && <Alert type="warning" showIcon message="共享电脑暂时离线" description="请检查局域网和素材库共享端。恢复后会自动检测连接。" />}
    {connection && projects.length > 0
      ? selectedProjectIds.length
        ? <SearchPage key={connection.prefix + selectedProjectIds.join(',')} projectIds={selectedProjectIds} />
        : <Card variant="borderless"><Empty description="请至少选择一个项目后再搜索" /></Card>
      : <Card variant="borderless"><Empty description={busy ? '正在连接并读取项目…' : connection ? '这台电脑的素材库还没有项目' : '连接共享电脑后，即可搜索标注素材、查看画面和播放命中片段'} /></Card>}
  </Flex>
}

createRoot(document.getElementById('root')!).render(
  <ConfigProvider locale={zhCN} theme={theme}><QueryClientProvider client={cache}><LanApp /></QueryClientProvider></ConfigProvider>,
)
