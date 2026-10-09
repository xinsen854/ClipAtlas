import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Modal, Space, Typography } from 'antd'

import { getLibraryItems, pauseLibraryProcessing, reparseLibraryItem, resetLibraryAnalysis } from '../../api/library'
import { libraryStatusLabels, type LibraryItemStatus } from '../../utils/statusMaps'
import { ErrorBlock } from '../../components/ErrorBlock'

const SCOPE_LABELS: Record<LibraryItemStatus, string> = {
  QUEUED: '等待项',
  PROBING: '读取视频信息项',
  SCENE_DETECTION: '镜头切分项',
  FRAME_EXTRACTION: '解析中项',
  COMPLETED: '已完成项',
  FAILED: '失败项',
  MISSING: '文件丢失项',
}

export function LibraryMaintenanceActions({ available, busy, onBusyChange, status }: {
  available: boolean; busy: boolean; onBusyChange?: (busy: boolean) => void; status?: LibraryItemStatus
}) {
  const client = useQueryClient()
  const cancel = useRef(false)
  const [confirm, setConfirm] = useState<'reset' | 'reparse' | null>(null)
  const [running, setRunning] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  useEffect(() => () => { cancel.current = true }, [])
  useEffect(() => { onBusyChange?.(running || resetting) }, [running, resetting, onBusyChange])

  const scopeLabel = status ? SCOPE_LABELS[status] ?? libraryStatusLabels[status] : '全部'

  async function reset() {
    setConfirm(null)
    setResetting(true)
    setError(null)
    setNotice('')
    try {
      const result = await resetLibraryAnalysis()
      await client.invalidateQueries()
      setNotice(result.warning ?? `已清空 ${result.items_reset} 个素材的解析结果与缓存，素材目录和原文件保留。点击“继续未完成”可开始解析。`)
    } catch (caught) { setError(caught) }
    finally { setResetting(false) }
  }

  async function reparseScope() {
    setConfirm(null)
    setRunning(true)
    setError(null)
    setNotice('')
    setProgress(`正在读取${scopeLabel}素材…`)
    cancel.current = false
    let done = 0
    let failed = 0
    try {
      client.setQueryData(['library', 'processing'], await pauseLibraryProcessing())
      const items: Awaited<ReturnType<typeof getLibraryItems>> = []
      for (let offset = 0; !cancel.current; offset += 500) {
        const page = await getLibraryItems({ status, limit: 500, offset })
        items.push(...page)
        if (page.length < 500) break
      }
      if (items.length === 0) {
        setNotice(`当前${scopeLabel}没有素材需要重新解析。`)
        return
      }
      if (items.some((item) => ['PROBING', 'SCENE_DETECTION', 'FRAME_EXTRACTION'].includes(item.status))) {
        throw new Error('有素材仍在解析，请等当前素材完成后重试。')
      }
      const candidates = items.filter((item) => item.status !== 'MISSING')
      for (const item of candidates) {
        if (cancel.current) break
        const name = item.source_path.replaceAll('\\', '/').split('/').at(-1)
        setProgress(`正在重新解析${scopeLabel} ${done + 1} / ${candidates.length}：${name}`)
        const result = await reparseLibraryItem(item.id)
        done += 1
        if (result.status !== 'COMPLETED') failed += 1
        await Promise.all([
          client.invalidateQueries({ queryKey: ['library', 'items'] }),
          client.invalidateQueries({ queryKey: ['library', 'summary'] }),
          client.invalidateQueries({ queryKey: ['video'] }),
        ])
      }
      setNotice(`${cancel.current ? '已停止' : `${scopeLabel}重新解析结束`}：已处理 ${done} 个，失败 ${failed} 个，跳过丢失素材 ${items.length - candidates.length} 个。`)
    } catch (caught) { setError(caught) }
    finally { setRunning(false); setProgress('') }
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Space wrap>
        <Button type="primary" disabled={!available || busy || resetting || running}
          onClick={() => setConfirm('reparse')}>
          {status ? `重新解析${scopeLabel}` : '全部重新解析'}
        </Button>
        <Button danger disabled={busy || resetting || running} loading={resetting}
          onClick={() => setConfirm('reset')}>清空解析结果与缓存</Button>
        {running ? <Button onClick={() => { cancel.current = true; setProgress('正在停止，等待当前素材完成…') }}>
          完成当前素材后停止
        </Button> : null}
        {progress ? <Typography.Text>{progress}</Typography.Text> : null}
      </Space>
      {running ? <Alert type="info" showIcon message={`正在逐个重新解析${scopeLabel}素材，请保持本页打开。后台自动解析已暂停。`} /> : null}
      {notice ? <Alert type="info" showIcon message={notice} /> : null}
      {error ? <ErrorBlock error={error} title="素材库操作未完成" /> : null}
      <Modal open={confirm !== null} title={confirm === 'reset' ? '确认清空全局解析结果与缓存？' : `确认重新解析${scopeLabel}？`}
        okText={confirm === 'reset' ? '确认清空' : (status ? `开始重新解析${scopeLabel}` : '开始全部重新解析')} cancelText="取消"
        okButtonProps={{ danger: confirm === 'reset' }} onCancel={() => setConfirm(null)}
        onOk={() => { if (confirm === 'reset') void reset(); else void reparseScope() }}>
        {confirm === 'reset' ? (
          <>
            <Typography.Paragraph strong>这是所有项目共享的素材库，不只是当前项目。</Typography.Paragraph>
            <Typography.Paragraph>此前的 Visual、ASR、OCR、Raw OCR、checkpoint、片段标注（含人工修正）和素材抽帧缓存都会清空，需要重新解析。</Typography.Paragraph>
            <Typography.Paragraph>原始素材文件、素材目录配置、项目、文案、旁白和已导出的草稿保留。旧粗剪不会自动更新。操作前自动备份数据库。</Typography.Paragraph>
          </>
        ) : (
          <Typography.Paragraph>
            {status
              ? `将逐个重跑当前筛选（${scopeLabel}）下的素材，包括已解析完成的素材。会重新调用已配置的 AI 服务并产生费用。`
              : '将逐个重跑全部可用素材的 Visual、ASR、OCR，包括已解析完成的素材。会重新调用已配置的 AI 服务并产生费用；旧 Visual 完成 checkpoint 不会被用于跳过本次解析。'}
          </Typography.Paragraph>
        )}
      </Modal>
    </Space>
  )
}
