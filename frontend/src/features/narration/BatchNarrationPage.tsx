import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Empty, Flex, Input, InputNumber, message, Modal, Segmented, Select, Space, Table, Tag, Typography, Upload } from 'antd'
import { Link } from 'react-router-dom'

import { ApiError } from '../../api/errors'
import {
  createNarrationBatch, generateBatchPlan, getNarrationBatch, importBatchAudio,
  listNarrationBatches, previewNarrationBatch,
  type BatchEntry, type BatchMatch, type BatchScript, type NarrationBatch,
} from '../../api/narrationBatches'
import { exportJianying } from '../../api/exports'
import { ErrorBlock } from '../../components/ErrorBlock'
import { PageHeader } from '../../components/PageHeader'
import { useAppStore } from '../../stores/useAppStore'
import { formatDuration } from '../../utils/format'

type ExportRatioOption = '16:9' | '9:16' | '1:1'
const EXPORT_RATIO_LABELS: Record<ExportRatioOption, string> = {
  '16:9': '横屏 16:9',
  '9:16': '竖屏 9:16',
  '1:1': '方屏 1:1',
}

export function BatchNarrationPage() {
  const projectId = useAppStore((state) => state.currentProjectId)
  return projectId ? <BatchWorkspace key={projectId} projectId={projectId} /> : <Empty description="请先选择项目" />
}

function BatchWorkspace({ projectId }: { projectId: string }) {
  const client = useQueryClient()
  const stop = useRef(false)
  const [batchId, setBatchId] = useState<string | null>(null)
  const [historyOffset, setHistoryOffset] = useState(0)
  const [name, setName] = useState('')
  const [markdown, setMarkdown] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [preview, setPreview] = useState<BatchMatch[]>([])
  const [assignments, setAssignments] = useState<Record<string, number | null>>({})
  const [topK, setTopK] = useState(12)
  const [exportRatio, setExportRatio] = useState<ExportRatioOption>('16:9')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [confirmation, setConfirmation] = useState<'import' | 'plan' | null>(null)
  useEffect(() => () => { stop.current = true }, [])
  // 自动预览：MD 和音频都就绪后，停顿片刻自动拆分并匹配，无需手动点按钮。
  useEffect(() => {
    if (batchId || busy || preview.length > 0 || !markdown.trim() || files.length === 0) return
    const timer = setTimeout(() => { void previewFiles() }, 400)
    return () => clearTimeout(timer)
  }, [markdown, files, batchId, busy, preview.length])

  const history = useQuery({ queryKey: ['project', projectId, 'narration-batches', historyOffset], queryFn: () => listNarrationBatches(projectId, historyOffset) })
  const batchQuery = useQuery({
    queryKey: ['narration-batch', projectId, batchId],
    queryFn: () => getNarrationBatch(projectId, batchId as string), enabled: Boolean(batchId),
  })
  const batch = batchQuery.data
  const selected = preview.map((row) => assignments[row.script.id])
  const matched = preview.length > 0 && selected.every((index) => index !== null && index !== undefined && files[index])
    && new Set(selected).size === selected.length
  const unused = files.length - new Set(selected.filter((index) => index !== null && index !== undefined)).size
  const readyPlans = batch?.entries.filter((entry) => entry.narration_track_id && !entry.plan_id) ?? []

  async function refresh(id: string) {
    const result = await getNarrationBatch(projectId, id)
    client.setQueryData(['narration-batch', projectId, id], result)
    return result
  }

  async function previewFiles() {
    setBusy(true); setError(null); setNotice('')
    try {
      const result = await previewNarrationBatch(projectId, markdown, files.map(({ name, size }) => ({ name, size })))
      setPreview(result)
      setAssignments(Object.fromEntries(result.map((row) => [row.script.id, row.audio_index])))
    } catch (caught) { setError(caught) }
    finally { setBusy(false) }
  }

  async function run(current: NarrationBatch, mode: 'import' | 'plan') {
    setBusy(true); setError(null); setNotice(''); stop.current = false
    let completed = 0
    let failed = 0
    let exportedOk = 0
    let exportFailed = 0
    const entries = current.entries.filter((entry) => mode === 'import'
      ? !entry.narration_track_id : entry.narration_track_id && !entry.plan_id)
    try {
      for (const entry of entries) {
        if (stop.current) break
        setProgress(`${mode === 'import' ? '导入旁白' : '生成粗剪并导入剪映'} ${completed + failed + 1}/${entries.length}：${entry.title}`)
        try {
          if (mode === 'import') {
            const candidates = files.filter((file) => file.name === entry.audio_name && file.size === entry.audio_size)
            if (candidates.length !== 1) throw new Error(`请重新选择唯一的音频文件：${entry.audio_name}`)
            await importBatchAudio(projectId, current.id, entry.id, candidates[0])
          } else {
            const plan = await generateBatchPlan(projectId, current.id, entry.id)
            if (plan?.id) {
              try {
                await exportJianying({ plan_id: plan.id })
                exportedOk += 1
              } catch (exportCaught) {
                exportFailed += 1
                setError(exportCaught)
              }
            }
          }
          completed += 1
        } catch (caught) {
          failed += 1
          setError(caught)
          // 单条失败不中断后续：只有用户手动停止或登录已过期才停（锁冲突 409等普通失败继续下一条）
          if (caught instanceof ApiError && [401, 403].includes(caught.status)) stop.current = true
        }
        await refresh(current.id)
      }
      setNotice(`${stop.current ? '已停止' : '本轮完成'}：成功 ${completed} 条，失败 ${failed} 条${mode === 'plan' ? `，自动导入剪映草稿 ${exportedOk} 条${exportFailed > 0 ? `，导出失败 ${exportFailed} 条` : ''}` : ''}。已完成结果已保存，继续执行会跳过已完成条目。`)
    } catch (caught) { setError(caught) }
    finally {
      setBusy(false); setProgress('')
      void client.invalidateQueries({ queryKey: ['project', projectId, 'narration-batches'] })
      void client.invalidateQueries({ queryKey: ['project', projectId, 'narrations'] })
    }
  }

  async function retryFailed(current: NarrationBatch) {
    const failed = current.entries.filter((entry) => entry.last_error)
    if (failed.length === 0) { void message.info('没有需要重试的条目'); return }
    setBusy(true); setError(null); setNotice(''); stop.current = false
    let completed = 0
    let failedCount = 0
    for (const entry of failed) {
      if (stop.current) break
      setProgress(`重试失败条目 ${completed + failedCount + 1}/${failed.length}：${entry.title}`)
      try {
        if (entry.narration_track_id && !entry.plan_id) {
          await generateBatchPlan(projectId, current.id, entry.id)
        } else if (!entry.narration_track_id) {
          const candidates = files.filter((file) => file.name === entry.audio_name && file.size === entry.audio_size)
          if (candidates.length !== 1) throw new Error(`请重新选择唯一的音频文件：${entry.audio_name}`)
          await importBatchAudio(projectId, current.id, entry.id, candidates[0])
        } else { continue }
        completed += 1
      } catch (caught) {
        failedCount += 1
        setError(caught)
        if (caught instanceof ApiError && [401, 403].includes(caught.status)) stop.current = true
      }
      await refresh(current.id)
    }
    setNotice(`${stop.current ? '已停止' : '重试完成'}：成功 ${completed} 条，失败 ${failedCount} 条。已成功结果已保存，继续执行会跳过已完成条目。`)
    setBusy(false); setProgress('')
    void client.invalidateQueries({ queryKey: ['project', projectId, 'narration-batches'] })
    void client.invalidateQueries({ queryKey: ['project', projectId, 'narrations'] })
  }

  async function confirmImport() {
    if (!matched) return
    setConfirmation(null); setBusy(true); setError(null)
    try {
      const created = await createNarrationBatch(projectId, {
        name, markdown, files: files.map(({ name, size }) => ({ name, size })), top_k: topK, export_ratio: exportRatio,
        assignments: preview.map((row) => ({ entry_id: row.script.id, audio_index: assignments[row.script.id] as number })),
      })
      client.setQueryData(['narration-batch', projectId, created.id], created)
      setBatchId(created.id)
      await run(created, 'import')
    } catch (caught) { setError(caught); setBusy(false) }
  }

  const rows: BatchScript[] = batchId ? batch?.entries ?? [] : preview.map((row) => row.script)
  const audioOptions = useMemo(
    () => files.map((file, index) => ({ value: index, label: `${file.name} · ${(file.size / 1024).toFixed(0)}KB` })),
    [files],
  )
  const columns = useMemo(() => [
            { title: '文案', key: 'script', width: 460, render: (_: unknown, row: BatchScript) => <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}><Typography.Text strong ellipsis style={{ maxWidth: 420 }}>{row.title}</Typography.Text><Typography.Paragraph type="secondary" ellipsis={{ rows: 2, tooltip: row.text }} style={{ maxWidth: 420, marginBottom: 0 }}>{row.text}</Typography.Paragraph></div> },
            { title: '对应旁白', key: 'audio', render: (_: unknown, row: BatchScript) => batchId ? (row as BatchEntry).audio_name : <Select aria-label={`文案 ${row.id} 的旁白`} allowClear value={assignments[row.id]} style={{ minWidth: 250 }}
              showSearch optionFilterProp="label"
              placeholder="请选择对应旁白" options={audioOptions}
              onChange={(value) => setAssignments((current) => ({ ...current, [row.id]: value ?? null }))} /> },
            { title: '状态', key: 'status', render: (_: unknown, row: BatchScript) => {
              if (!batchId) { const original = preview.find((item) => item.script.id === row.id); return <Tag>{assignments[row.id] != null && assignments[row.id] !== original?.audio_index ? '手动指定' : original?.reason}</Tag> }
              const entry = row as BatchEntry
              return <Space direction="vertical"><Tag color={entry.last_error ? 'error' : entry.plan_id ? 'success' : 'default'}>{entry.last_error ? '需要重试' : entry.plan_id ? '粗剪完成' : entry.narration_track_id ? '旁白已导入' : '等待导入'}</Tag>
                {entry.duration_ms != null ? <Typography.Text>{formatDuration(entry.duration_ms)}</Typography.Text> : null}
                {entry.last_error ? <Typography.Text type="danger">{entry.last_error}</Typography.Text> : null}
                {entry.plan_id ? <Link to={`/rough-cut/${entry.plan_id}`}>查看粗剪与导出</Link> : null}</Space>
            } },
          ], [batchId, rows, assignments, audioOptions, preview])
  return (
    <Flex vertical gap={20}>
      <PageHeader title="批量文案与真人旁白" description="一个MD拆成多条文案，按编号、唯一标题或首段匹配旁白；确认后逐条处理，每批最多100条。"
        extra={<Link to="/narration"><Button>返回单条文案与旁白</Button></Link>} />
      <Card title="已保存批次">
        <Space wrap>
          <Select aria-label="已保存批次" placeholder="选择批次继续处理" value={batchId} disabled={busy}
            showSearch optionFilterProp="label"
            loading={history.isFetching} style={{ minWidth: 300 }}
            options={history.data?.map((item) => ({ value: item.id, label: `${item.name} · ${item.entry_count}条` }))}
            onChange={(value) => { setBatchId(value); setFiles([]); setError(null); setNotice('') }} />
          <Button disabled={busy || historyOffset === 0} onClick={() => setHistoryOffset(historyOffset - 20)}>上一批列表</Button>
          <Button disabled={busy || (history.data?.length ?? 0) < 20} onClick={() => setHistoryOffset(historyOffset + 20)}>下一批列表</Button>
          <Button disabled={busy} onClick={() => { setBatchId(null); setPreview([]); setFiles([]); setMarkdown(''); setName(''); setNotice(''); setError(null) }}>新建批次</Button>
        </Space>
      </Card>
      <Card title={batch ? `${batch.name} · ${batch.entries.length}条${batch.export_ratio ? ` · 导出比例 ${batch.export_ratio}` : ''}` : '1. 选择MD和旁白文件'}>
        <Flex vertical gap={12}>
          {!batchId ? <>
            <Typography.Text>支持“## 001 标题”、顶层“1. / 2. / 3.”、“一、二、三、”、“文案1：”或“第1条：”，也支持用 --- 分隔。建议旁白命名为“001_标题.wav”。</Typography.Text>
            <Typography.Text type="secondary">普通空行和正文内的小数不会拆成新文案；标题与长正文在同一行时保留完整内容。可以先不选音频，只预览拆分数量与正文。</Typography.Text>
            <input key={batchId ?? 'new-md'} aria-label="批量MD文案" type="file" accept=".md,.txt,text/markdown,text/plain" disabled={busy}
              onChange={async (event) => {
                const file = event.target.files?.[0]
                if (!file) return
                if (file.size > 8_000_000) { setError(new Error('MD文件不能超过8MB')); return }
                try { setMarkdown(await file.text()); setName(file.name.replace(/\.[^.]+$/, '')); setPreview([]) }
                catch (caught) { setError(caught) }
              }} />
            <Input aria-label="批次名称" placeholder="批次名称" value={name} disabled={busy} maxLength={200} onChange={(event) => setName(event.target.value)} />
            <Space><Typography.Text>每条文案 Top-K</Typography.Text><InputNumber aria-label="批量Top-K" min={1} max={100} precision={0} value={topK} disabled={busy} onChange={(value) => setTopK(value ?? 12)} /></Space>
            <Space wrap><Typography.Text>本批导出画面比例</Typography.Text>
              <Segmented<ExportRatioOption> aria-label="批量导出比例" value={exportRatio} disabled={busy}
                options={(Object.keys(EXPORT_RATIO_LABELS) as ExportRatioOption[]).map((key) => ({ value: key, label: EXPORT_RATIO_LABELS[key] }))}
                onChange={(value) => setExportRatio(value)} />
              <Typography.Text type="secondary">导出草稿时统一使用此比例，不再逐个选择。</Typography.Text>
            </Space>
          </> : null}
          <Upload.Dragger aria-label="批量真人旁白文件" accept="audio/*" multiple disabled={busy}
            showUploadList={false}
            onChange={(info) => {
              const incoming = info.fileList
                .map((item) => item.originFileObj)
                .filter((item): item is NonNullable<typeof item> => Boolean(item))
              setFiles((current) => {
                const known = new Set(current.map((item) => `${item.name}:${item.size}`))
                const merged = [...current]
                for (const item of incoming) {
                  if (known.has(`${item.name}:${item.size}`)) continue
                  known.add(`${item.name}:${item.size}`)
                  merged.push(item)
                }
                return merged.slice(0, 100)
              })
              if (info.fileList.length > 100) setError(new Error('每批最多选择100个音频文件'))
              if (!batchId) setPreview([])
            }}>
            <Typography.Title level={5} style={{ margin: 0 }}>点击选择，或把音频文件拖到这里</Typography.Title>
            <Typography.Text type="secondary">支持批量拖拽（一次可拖入几十个音频），重复拖入同一文件会自动去重；已导入的音频无需重复上传。</Typography.Text>
          </Upload.Dragger>
          <Typography.Text type="secondary">已选择 {files.length} 个音频。继续未完成的导入时，请重新选择原音频文件；已导入的音频无需重复上传。</Typography.Text>
          {!batchId ? <Button type="primary" disabled={busy} onClick={() => {
            if (!markdown.trim()) { void message.warning('请先选择包含文案的 MD 文件（支持 .md / .txt）'); return }
            void previewFiles()
          }}>拆分并预览匹配</Button> : null}
        </Flex>
      </Card>
      {error || history.error || batchQuery.error ? <ErrorBlock error={error ?? history.error ?? batchQuery.error} title="批量处理需要检查" /> : null}
      <div style={{ minHeight: busy || notice ? 78 : 0 }}>
        {notice ? <Alert type="info" showIcon message={notice} style={{ minHeight: 72 }} /> : null}
        {busy ? <Alert type="info" showIcon
          message={<Typography.Text ellipsis style={{ maxWidth: 'calc(100vw - 480px)' }}>{progress || '正在处理…'}</Typography.Text>}
          description="请保持本页打开。停止或离开页面后，当前条目会完成，后续条目不再发起。"
          style={{ minHeight: 72 }} /> : null}
      </div>
      <Card title="2. 核对文案与旁白配对">
        <Typography.Paragraph type="secondary">按文件名匹配，不识别音频内容。请核对标题和正文；缺失、重复或多候选不会自动猜测。展开一行可查看正文。</Typography.Paragraph>
        {!batchId && preview.length > 0 ? <Alert type={matched ? 'success' : 'warning'} showIcon
          message={`识别到 ${preview.length} 条文案，${files.length} 个旁白；${matched ? '配对完整，等待确认' : '请补全一一对应的配对'}`}
          description={unused > 0 ? `${unused} 个未使用的音频不会导入。` : undefined} /> : null}
        <Table<BatchScript> rowKey="id" dataSource={rows} pagination={{ pageSize: 10, showSizeChanger: false }} scroll={{ y: 540 }} loading={batchQuery.isFetching}
          expandable={{ expandedRowRender: (row) => <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>{row.text}</Typography.Paragraph> }}
          columns={columns} />
        <Space wrap>
          {!batchId ? <Button type="primary" disabled={busy || !matched} onClick={() => {
            if (!markdown.trim()) { void message.warning('请先选择包含文案的 MD 文件'); return }
            if (!name.trim()) { void message.warning('请填写批次名称'); return }
            if (!matched) { void message.warning('请先拆分并预览匹配，补全每条文案对应的旁白'); return }
            setConfirmation('import')
          }}>确认配对并批量导入旁白</Button> : <>
            <Button disabled={busy || !batch || !batch.entries.some((entry) => !entry.narration_track_id)} onClick={() => batch && void run(batch, 'import')}>继续导入未完成旁白</Button>
            <Button type="primary" disabled={busy || readyPlans.length === 0} onClick={() => setConfirmation('plan')}>串行生成就绪条目的粗剪</Button>
            <Button disabled={busy || !batch || !batch.entries.some((entry) => entry.last_error)} onClick={() => batch && void retryFailed(batch)}>重试失败条目</Button>
          </>}
          {busy ? <Button onClick={() => { stop.current = true }}>完成当前条目后停止</Button> : null}
        </Space>
      </Card>
      <Modal open={confirmation !== null} title={confirmation === 'import' ? '确认文案与旁白配对？' : '确认串行生成粗剪？'}
        okText={confirmation === 'import' ? '确认并导入' : '确认并生成'} cancelText="取消" onCancel={() => setConfirmation(null)}
        onOk={() => {
          if (confirmation === 'import') void confirmImport()
          else { setConfirmation(null); if (batch) void run(batch, 'plan') }
        }}>
        <Typography.Paragraph>{confirmation === 'import'
          ? `将保存并逐个导入 ${preview.length} 条已匹配文案和旁白，${Math.max(0, unused)} 个未使用的音频不导入。每条独立保存，导入音频本身不调用AI。`
          : `将为 ${readyPlans.length} 条已导入旁白串行生成粗剪，使用当前项目规则和共享素材索引，会调用已配置的AI服务并产生费用。已完成结果不会重复生成。`}</Typography.Paragraph>
      </Modal>
    </Flex>
  )
}
