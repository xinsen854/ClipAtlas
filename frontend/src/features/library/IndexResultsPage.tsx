import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Card, Empty, Flex, Space, Tabs, Tag, Typography } from 'antd'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { getLibraryItem, getVideoIndexResults, type IndexSource } from '../../api/library'
import { ErrorBlock } from '../../components/ErrorBlock'
import { LoadingBlock } from '../../components/LoadingBlock'
import { PageHeader } from '../../components/PageHeader'
import { formatDuration, formatTimeRange } from '../../utils/format'
import { isLibraryItemPending } from '../../utils/statusMaps'

const PAGE_SIZE = 10
const statuses: Record<string, string> = {
  completed: '已完成', processing: '处理中', failed: '失败', untracked: '无 checkpoint',
}
const pollutionLabels = { clean: '画面干净', text_heavy: '文字较多', blocked: '不适合剪辑' }

function ResultsList({ videoId, source, polling }: { videoId: string; source: IndexSource; polling: boolean }) {
  const [offset, setOffset] = useState(0)
  const query = useQuery({
    queryKey: ['video', videoId, 'index-results', source, offset],
    queryFn: () => getVideoIndexResults(videoId, source, PAGE_SIZE, offset),
    refetchInterval: polling ? 5000 : false,
  })

  return (
    <Flex vertical gap={16}>
      <Flex justify="space-between" align="center" gap={12} wrap>
        <Typography.Text type="secondary">
          {source === 'summary'
            ? '按画面连续性合并相邻片段，最长约 30 秒；展示综合描述和关键语义。'
            : source === 'visual'
            ? 'Visual 为视频向量索引；缩略图取自对应场景的已有缓存帧。'
            : '展示已保存的识别结果，不同修订分别列出。'}
        </Typography.Text>
        <Button onClick={() => void query.refetch()} loading={query.isFetching}>刷新结果</Button>
      </Flex>
      {query.isPending ? <LoadingBlock label="正在读取解析结果…" /> : null}
      {query.error ? <ErrorBlock error={query.error} title="解析结果读取失败" /> : null}
      {query.data && !query.data.items.length ? <Empty description="暂无已保存的解析结果" /> : null}
      {query.data?.items.map((item, index) => 'summary' in item ? (
        <Card key={offset + '-' + index} size="small" title={formatTimeRange(item.start_ms, item.end_ms)}>
          <Flex vertical gap={12}>
            <Space wrap>
              {item.presentation_type ? <Tag color="blue">{item.presentation_type}</Tag> : null}
              <Tag color={item.pollution_level === 'blocked' ? 'error' : item.pollution_level === 'text_heavy' ? 'warning' : 'success'}>
                {pollutionLabels[item.pollution_level]}
              </Tag>
            </Space>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: 0 }}>
              {item.summary || '暂无综合描述'}
            </Typography.Paragraph>
            {([
              ['主体', item.subjects], ['动作', item.actions], ['场景', item.scenes],
            ] as [string, string[]][]).map(([label, values]) => values.length ? (
              <Space key={label} wrap size={[4, 8]}>
                <Typography.Text type="secondary">{label}</Typography.Text>
                {values.slice(0, 6).map((value) => <Tag key={value}>{value}</Tag>)}
                {values.length > 6 ? <Tag>+{values.length - 6}</Tag> : null}
              </Space>
            ) : null)}
          </Flex>
        </Card>
      ) : (
        <Card key={`${offset}-${index}`} size="small" title={formatTimeRange(item.start_ms, item.end_ms)}>
          <Flex vertical gap={12}>
            <Space wrap>
              <Tag color={item.status === 'failed' ? 'error' : item.status === 'completed' ? 'success' : 'default'}>
                {statuses[item.status] ?? item.status} · {item.status}
              </Tag>
              <Typography.Text>provider: {item.provider}</Typography.Text>
              <Typography.Text>model: {item.model}</Typography.Text>
              {'revision' in item ? <Tag>revision: {item.revision}</Tag> : null}
            </Space>
            <Typography.Text type="secondary">
              start_ms: {item.start_ms} · end_ms: {item.end_ms}
            </Typography.Text>
            {'dimensions' in item ? (
              <Flex gap={16} align="center" wrap>
                {item.thumbnail_url ? (
                  <img
                    src={item.thumbnail_url}
                    alt={`${formatTimeRange(item.start_ms, item.end_ms)} 对应场景缓存帧`}
                    loading="lazy"
                    width={180}
                    style={{ maxHeight: 110, objectFit: 'contain', borderRadius: 6 }}
                  />
                ) : <Typography.Text type="secondary">无可用缓存缩略图</Typography.Text>}
                <Space direction="vertical" size={4}>
                  <Typography.Text>dimensions: {item.dimensions ?? '无已存储向量'}</Typography.Text>
                  <Typography.Text type="secondary">
                    窗口 {item.chunk_duration_ms} ms · 重叠 {item.overlap_ms} ms
                  </Typography.Text>
                </Space>
              </Flex>
            ) : null}
            {'sentences' in item ? (
              item.sentences.length ? item.sentences.map((sentence, sentenceIndex) => (
                <Flex key={sentenceIndex} gap={16} wrap>
                  <Typography.Text type="secondary">
                    {formatTimeRange(sentence.start_ms, sentence.end_ms)}
                  </Typography.Text>
                  <Typography.Text style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                    {sentence.text}
                  </Typography.Text>
                </Flex>
              )) : <Typography.Text type="secondary">无已识别句子</Typography.Text>
            ) : null}
            {'readable_text' in item ? (
              <>
                <Typography.Text type="secondary">
                  采样时间 {formatDuration(item.start_ms)} · 间隔 {item.interval_ms} ms
                </Typography.Text>
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: 0 }}>
                  {item.readable_text || '未识别到可读文字'}
                </Typography.Paragraph>
                <details>
                  <summary style={{ cursor: 'pointer' }}>查看原始 OCR 文本</summary>
                  <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 320, overflow: 'auto' }}>
                    {item.text || '（空）'}
                  </pre>
                </details>
              </>
            ) : null}
            {item.last_error ? <Typography.Text type="danger">{item.last_error}</Typography.Text> : null}
          </Flex>
        </Card>
      ))}
      <Space wrap>
        <Button disabled={offset === 0 || query.isFetching} onClick={() => setOffset(offset - PAGE_SIZE)}>
          上一页
        </Button>
        <Typography.Text>第 {offset / PAGE_SIZE + 1} 页 · 每页 {PAGE_SIZE} 条</Typography.Text>
        <Button disabled={!query.data?.has_more || query.isFetching || query.isError} onClick={() => setOffset(offset + PAGE_SIZE)}>
          下一页
        </Button>
      </Space>
    </Flex>
  )
}

export function IndexResultsPage() {
  const { itemId } = useParams<{ itemId: string }>()
  const [searchParams] = useSearchParams()
  const fromStatus = searchParams.get('fromStatus')
  const [source, setSource] = useState<IndexSource>('visual')
  const itemQuery = useQuery({
    queryKey: ['library', 'item', itemId],
    queryFn: () => getLibraryItem(itemId as string),
    enabled: Boolean(itemId),
    refetchInterval: (query) => isLibraryItemPending(query.state.data?.status) ? 5000 : false,
  })
  if (!itemId) return <ErrorBlock error={new Error('missing item id')} title="素材地址无效" />
  if (itemQuery.isPending) return <LoadingBlock label="正在读取素材…" />
  if (itemQuery.error) return <ErrorBlock error={itemQuery.error} title="素材读取失败" />
  const item = itemQuery.data
  if (!item) return <Empty description="素材不存在" />
  const videoId = item.prepared_video_id ?? item.video_id
  const filename = item.source_path.replaceAll('\\', '/').split('/').at(-1)

  return (
    <Flex vertical gap={20}>
      <PageHeader
        title={`${filename} · 解析结果`}
        description="查看 Visual 视频向量、ASR 语音识别和 OCR 画面文字。"
        extra={
          <Space wrap>
            <Link to={`/library/items/${item.id}/segments${fromStatus ? `?fromStatus=${fromStatus}` : ''}`}><Button>片段标注与人工修正</Button></Link>
            <Link to={`/library/items/${item.id}${fromStatus ? `?fromStatus=${fromStatus}` : ''}`}><Button>返回素材详情</Button></Link>
          </Space>
        }
      />
      <Card variant="borderless">
        <Tabs
          activeKey={source}
          onChange={(key) => setSource(key as IndexSource)}
          items={(['visual', 'summary', 'asr', 'ocr'] as IndexSource[]).map((key) => ({
            key, label: key === 'visual' ? 'Visual' : key === 'summary' ? '综合描述' : key.toUpperCase(),
          }))}
        />
        {videoId ? (
          <ResultsList key={`${videoId}:${source}`} videoId={videoId} source={source} polling={isLibraryItemPending(item.status)} />
        ) : <Empty description="素材尚未生成视频记录" />}
      </Card>
    </Flex>
  )
}
