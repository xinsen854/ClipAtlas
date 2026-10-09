import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  Button,
  Card,
  Descriptions,
  Empty,
  Flex,
  Input,
  Radio,
  Space,
  Tag,
  Typography,
} from 'antd'

import {
  searchHybrid,
  searchSegments,
  searchVideoChunks,
  type HybridSearchHit,
  type SemanticSearchHit,
  type VideoChunkSearchHit,
  type VideoSearchGranularity,
} from '../../api/search'
import { ErrorBlock } from '../../components/ErrorBlock'
import { PageHeader } from '../../components/PageHeader'
import { SearchHitPreview } from './SearchHitPreview'
import { useAppStore } from '../../stores/useAppStore'
import { readableSourcePath } from '../../utils/sourcePath'

const SEARCH_LIMIT = 20

type SearchMode = 'hybrid' | 'video-5s' | 'video-30s' | 'semantic'
type SearchRequest = { q: string; mode: SearchMode }
type SearchResult =
  | { kind: 'hybrid'; hits: HybridSearchHit[] }
  | { kind: 'video'; hits: VideoChunkSearchHit[] }
  | { kind: 'semantic'; hits: SemanticSearchHit[] }

type ScoredHit = {
  video_id: string
  source_start_ms: number
  source_end_ms: number
  score: number
}

export function mergeProjectHits<T extends ScoredHit>(groups: T[][], limit = SEARCH_LIMIT): T[] {
  const unique = new Map<string, T>()
  for (const hit of groups.flat()) {
    const key = `${hit.video_id}:${hit.source_start_ms}:${hit.source_end_ms}`
    const previous = unique.get(key)
    if (!previous || hit.score > previous.score) unique.set(key, hit)
  }
  return [...unique.values()].sort((left, right) => right.score - left.score).slice(0, limit)
}

function filenameFromSourceUri(sourceUri: string): string {
  const normalized = readableSourcePath(sourceUri).replaceAll('\\', '/')
  return normalized.split('/').filter(Boolean).at(-1) ?? sourceUri
}

function formatTimestamp(ms: number): string {
  const totalSeconds = ms / 1000
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds - minutes * 60
  return `${String(minutes).padStart(2, '0')}:${seconds.toFixed(3).padStart(6, '0')}`
}

function TagGroup({ values }: { values: string[] }) {
  if (!values.length) return <Typography.Text type="secondary">—</Typography.Text>
  return (
    <Space size={[4, 4]} wrap>
      {values.map((value, index) => (
        <Tag key={`${value}-${index}`}>{value}</Tag>
      ))}
    </Space>
  )
}

function originLabel(hit: SemanticSearchHit): string {
  return hit.annotation.origin === 'human' ? '人工修正' : 'AI 标注'
}

function HybridHitCard({ hit, index }: { hit: HybridSearchHit; index: number }) {
  return (
    <Card
      key={`${hit.video_id}-${hit.source_start_ms}-${hit.source_end_ms}`}
      variant="borderless"
      title={
        <Space wrap>
          <Typography.Text strong>{hit.filename}</Typography.Text>
          <Tag>{`#${index + 1}`}</Tag>
          <Tag>{`综合分数 ${hit.score.toFixed(4)}`}</Tag>
          {hit.visual_score !== null ? <Tag>{`视觉 ${hit.visual_score.toFixed(4)}`}</Tag> : null}
          {hit.asr_score !== null ? <Tag>{`ASR ${hit.asr_score.toFixed(4)}`}</Tag> : null}
          {hit.ocr_score !== null ? <Tag>{`OCR ${hit.ocr_score.toFixed(4)}`}</Tag> : null}
        </Space>
      }
    >
      <Flex vertical gap={10}>
        <SearchHitPreview videoId={hit.video_id} startMs={hit.source_start_ms} endMs={hit.source_end_ms} />
        <Typography.Text type="secondary">
          {formatTimestamp(hit.source_start_ms)} — {formatTimestamp(hit.source_end_ms)}
        </Typography.Text>
        {hit.asr_texts.length ? (
          <Flex gap={8} wrap>
            <Typography.Text type="secondary">ASR 命中</Typography.Text>
            <TagGroup values={hit.asr_texts} />
          </Flex>
        ) : null}
        {hit.ocr_texts.length ? (
          <Flex gap={8} wrap>
            <Typography.Text type="secondary">OCR 命中</Typography.Text>
            <TagGroup values={hit.ocr_texts} />
          </Flex>
        ) : null}
        <Typography.Text copyable={{ text: readableSourcePath(hit.source_uri) }}>{readableSourcePath(hit.source_uri)}</Typography.Text>
      </Flex>
    </Card>
  )
}

function VideoHitCard({ hit, index }: { hit: VideoChunkSearchHit; index: number }) {
  const vectorLabel = hit.chunk_duration_ms === 30_000 ? '30秒向量' : '5秒向量'
  return (
    <Card
      key={`${hit.video_id}-${hit.source_start_ms}-${hit.source_end_ms}`}
      variant="borderless"
      title={
        <Space wrap>
          <Typography.Text strong>{hit.filename}</Typography.Text>
          <Tag>{`#${index + 1}`}</Tag>
          <Tag>{`匹配分数 ${hit.score.toFixed(4)}`}</Tag>
          <Tag>{vectorLabel}</Tag>
        </Space>
      }
    >
      <Flex vertical gap={10}>
        <SearchHitPreview videoId={hit.video_id} startMs={hit.source_start_ms} endMs={hit.source_end_ms} />
        <Typography.Text type="secondary">
          {formatTimestamp(hit.source_start_ms)} — {formatTimestamp(hit.source_end_ms)}
        </Typography.Text>
        <Typography.Text copyable={{ text: readableSourcePath(hit.source_uri) }}>{readableSourcePath(hit.source_uri)}</Typography.Text>
      </Flex>
    </Card>
  )
}

function SemanticHitCard({
  hit,
  index,
  expanded,
  onToggle,
}: {
  hit: SemanticSearchHit
  index: number
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <Card
      key={hit.segment_id}
      variant="borderless"
      title={
        <Space wrap>
          <Typography.Text strong>{filenameFromSourceUri(hit.source_uri)}</Typography.Text>
          <Tag>{`#${index + 1}`}</Tag>
          <Tag>{`匹配分数 ${hit.score.toFixed(4)}`}</Tag>
          <Tag>{originLabel(hit)}</Tag>
        </Space>
      }
      extra={
        <Button size="small" onClick={onToggle}>
          {expanded ? '收起标注' : '查看标注'}
        </Button>
      }
    >
      <Flex vertical gap={12}>
        <SearchHitPreview videoId={hit.video_id} startMs={hit.source_start_ms} endMs={hit.source_end_ms} />
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          {hit.effective_description}
        </Typography.Paragraph>
        <Typography.Text type="secondary">
          {formatTimestamp(hit.source_start_ms)} — {formatTimestamp(hit.source_end_ms)}
        </Typography.Text>
        <Flex gap={12} wrap>
          <Space size={[4, 4]} wrap>
            <Typography.Text type="secondary">人物</Typography.Text>
            <TagGroup values={hit.annotation.characters} />
          </Space>
          <Space size={[4, 4]} wrap>
            <Typography.Text type="secondary">动作</Typography.Text>
            <TagGroup values={hit.annotation.actions} />
          </Space>
          <Space size={[4, 4]} wrap>
            <Typography.Text type="secondary">场景</Typography.Text>
            <TagGroup values={hit.annotation.scene} />
          </Space>
          <Space size={[4, 4]} wrap>
            <Typography.Text type="secondary">情绪</Typography.Text>
            <TagGroup values={hit.annotation.emotions} />
          </Space>
        </Flex>

        {expanded ? (
          <Descriptions column={{ xs: 1, md: 2 }} size="small" bordered>
            <Descriptions.Item label="物体">
              <TagGroup values={hit.annotation.objects} />
            </Descriptions.Item>
            <Descriptions.Item label="画面文字 / OCR">
              <TagGroup values={hit.annotation.ocr} />
            </Descriptions.Item>
            <Descriptions.Item label="镜头类型">
              {hit.annotation.shot_type ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="运镜">
              {hit.annotation.camera_motion ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="置信度">
              {hit.annotation.confidence === null
                ? '—'
                : `${(hit.annotation.confidence * 100).toFixed(0)}%`}
            </Descriptions.Item>
            <Descriptions.Item label="修订">
              {`修订 ${hit.annotation.revision}`}
            </Descriptions.Item>
            <Descriptions.Item label="锁定状态">
              {hit.annotation.locked ? '已锁定' : '未锁定'}
            </Descriptions.Item>
            <Descriptions.Item label="来源路径">
              <Typography.Text copyable={{ text: readableSourcePath(hit.source_uri) }}>{readableSourcePath(hit.source_uri)}</Typography.Text>
            </Descriptions.Item>
          </Descriptions>
        ) : null}
      </Flex>
    </Card>
  )
}

type SearchPageProps = {
  projectIds?: string[]
}

export function SearchPage({ projectIds }: SearchPageProps = {}) {
  const currentProjectId = useAppStore((state) => state.currentProjectId)
  const [query, setQuery] = useState('')
  const [searchMode, setSearchMode] = useState<SearchMode>('hybrid')
  const [expandedSegmentId, setExpandedSegmentId] = useState<string | null>(null)

  async function acrossProjects<T extends ScoredHit>(
    search: (projectId?: string) => Promise<T[]>,
  ): Promise<T[]> {
    if (projectIds === undefined) return search(currentProjectId ?? undefined)
    if (!projectIds.length) return []
    return mergeProjectHits(await Promise.all(projectIds.map((projectId) => search(projectId))))
  }

  const searchMutation = useMutation<SearchResult, Error, SearchRequest>({
    mutationFn: async ({ q, mode }) => {
      if (mode === 'hybrid') {
        return {
          kind: 'hybrid',
          hits: await acrossProjects((projectId) => searchHybrid({
            q, limit: SEARCH_LIMIT, ...(projectId ? { projectId } : {}),
          })),
        }
      }
      if (mode === 'semantic') {
        return {
          kind: 'semantic',
          hits: await acrossProjects((projectId) => searchSegments({
            q, limit: SEARCH_LIMIT, ...(projectId ? { projectId } : {}),
          })),
        }
      }
      const granularity: VideoSearchGranularity = mode === 'video-30s' ? '30s' : '5s'
      return {
        kind: 'video',
        hits: await acrossProjects((projectId) => searchVideoChunks({
          q, limit: SEARCH_LIMIT, granularity, ...(projectId ? { projectId } : {}),
        })),
      }
    },
    onSuccess: () => setExpandedSegmentId(null),
  })

  function submitSearch() {
    if (!query.trim()) return
    searchMutation.mutate({ q: query, mode: searchMode })
  }

  const result = searchMutation.data
  const hitCount = result?.hits.length ?? 0

  return (
    <Flex vertical gap={20}>
      <PageHeader
        title="素材搜索"
        description="默认使用视觉 + ASR + OCR 混合召回；也可切换查看单独视频向量或历史语义标注。"
      />

      <Card variant="borderless">
        <Flex vertical gap={12}>
          <Radio.Group
            value={searchMode}
            onChange={(event) => setSearchMode(event.target.value as SearchMode)}
          >
            <Radio.Button value="hybrid">混合召回</Radio.Button>
            <Radio.Button value="video-5s">视频向量 · 5 秒</Radio.Button>
            <Radio.Button value="video-30s">视频向量 · 30 秒</Radio.Button>
            <Radio.Button value="semantic">深度语义标注</Radio.Button>
          </Radio.Group>
          <Input.TextArea
            aria-label="搜索素材"
            value={query}
            rows={3}
            placeholder="例如：越野测试；雨夜里有人撑伞等公交；画面出现某个地名或参数……"
            onChange={(event) => setQuery(event.target.value)}
            onPressEnter={(event) => {
              if (!event.shiftKey) {
                event.preventDefault()
                submitSearch()
              }
            }}
          />
          <Flex justify="space-between" align="center" gap={12} wrap>
            <Typography.Text type="secondary">
              混合召回会合并视觉、语音和画面文字证据；不会在这里触发 qwen3.8 深度分析。
            </Typography.Text>
            <Button
              aria-label="搜索"
              type="primary"
              loading={searchMutation.isPending}
              disabled={!query.trim()}
              onClick={submitSearch}
            >
              搜索
            </Button>
          </Flex>
        </Flex>
      </Card>

      {searchMutation.error ? <ErrorBlock error={searchMutation.error} title="素材搜索失败" /> : null}

      {searchMutation.isIdle ? (
        <Card variant="borderless">
          <Empty description="输入描述后开始素材搜索" />
        </Card>
      ) : null}

      {searchMutation.isSuccess && hitCount === 0 ? (
        <Card variant="borderless">
          <Empty description="没有找到匹配素材" />
        </Card>
      ) : null}

      {result?.kind === 'hybrid'
        ? result.hits.map((hit, index) => (
            <HybridHitCard
              key={`${hit.video_id}-${hit.source_start_ms}-${hit.source_end_ms}`}
              hit={hit}
              index={index}
            />
          ))
        : null}

      {result?.kind === 'video'
        ? result.hits.map((hit, index) => <VideoHitCard key={`${hit.video_id}-${hit.source_start_ms}-${hit.source_end_ms}`} hit={hit} index={index} />)
        : null}

      {result?.kind === 'semantic'
        ? result.hits.map((hit, index) => (
            <SemanticHitCard
              key={hit.segment_id}
              hit={hit}
              index={index}
              expanded={expandedSegmentId === hit.segment_id}
              onToggle={() =>
                setExpandedSegmentId(expandedSegmentId === hit.segment_id ? null : hit.segment_id)
              }
            />
          ))
        : null}
    </Flex>
  )
}
