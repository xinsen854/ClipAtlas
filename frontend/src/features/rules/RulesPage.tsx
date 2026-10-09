import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { App as AntdApp, Alert, Button, Card, Empty, Flex, Input, Select, Space, Switch, Tag, Typography } from 'antd'

import {
  activateProjectRulePack,
  analyzeProjectRules,
  listProjectRulePacks,
  previewProjectRules,
  saveProjectRuleDraft,
  type ProjectRule,
  type ProjectRulePack,
  type ProjectedText,
  type RuleKind,
} from '../../api/rules'
import { ErrorBlock } from '../../components/ErrorBlock'
import { LoadingBlock } from '../../components/LoadingBlock'
import { PageHeader } from '../../components/PageHeader'
import { useAppStore } from '../../stores/useAppStore'

const ruleKindOptions: Array<{ value: RuleKind; label: string }> = [
  { value: 'pronunciation', label: '朗读发音' },
  { value: 'speech_suppress', label: '旁白不朗读' },
  { value: 'speech_replace', label: '旁白替换' },
  { value: 'subtitle_replace', label: '字幕替换' },
  { value: 'entity_alias', label: '检索别名' },
  { value: 'semantic_hint', label: '语义提示' },
]

function kindUsesReplacement(kind: RuleKind): boolean {
  return ['pronunciation', 'speech_replace', 'subtitle_replace', 'entity_alias'].includes(kind)
}

function kindUsesMatch(kind: RuleKind): boolean {
  return kind !== 'semantic_hint'
}

function normalizeRuleForKind(rule: ProjectRule, kind: RuleKind): ProjectRule {
  if (kind === 'semantic_hint') {
    return { kind, hint: rule.hint ?? '', enabled: rule.enabled }
  }
  if (kind === 'speech_suppress') {
    return { kind, match: rule.match ?? '', enabled: rule.enabled }
  }
  return {
    kind,
    match: rule.match ?? '',
    replacement: rule.replacement ?? '',
    enabled: rule.enabled,
  }
}

function packLabel(pack: ProjectRulePack): string {
  return pack.status === 'active'
    ? `修订 ${pack.revision} · 当前生效`
    : `修订 ${pack.revision} · 草稿`
}

export function RulesPage() {
  const queryClient = useQueryClient()
  const { message } = AntdApp.useApp()
  const projectId = useAppStore((state) => state.currentProjectId)
  const [instructions, setInstructions] = useState('')
  const [candidateRules, setCandidateRules] = useState<ProjectRule[]>([])
  const [previewText, setPreviewText] = useState('')
  const [previewResult, setPreviewResult] = useState<ProjectedText | null>(null)
  const [localPacks, setLocalPacks] = useState<ProjectRulePack[]>([])
  const [busy, setBusy] = useState<'analyze' | 'preview' | 'save' | `activate:${number}` | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)

  const packsQuery = useQuery({
    queryKey: ['project', projectId, 'rules'],
    queryFn: () => listProjectRulePacks(projectId as string),
    enabled: Boolean(projectId),
  })

  useEffect(() => {
    setInstructions('')
    setCandidateRules([])
    setPreviewText('')
    setPreviewResult(null)
    setLocalPacks([])
    setNotice(null)
    setActionError(null)
    setBusy(null)
  }, [projectId])

  useEffect(() => {
    if (packsQuery.data) setLocalPacks(packsQuery.data)
  }, [packsQuery.data])

  const orderedPacks = useMemo(
    () => [...localPacks].sort((a, b) => b.revision - a.revision),
    [localPacks],
  )

  if (!projectId) {
    return (
      <Flex vertical gap={20}>
        <PageHeader
          title="本批附加规则"
          description="规则按当前项目隔离，请先在顶部选择一个项目。"
        />
        <Card variant="borderless">
          <Empty description="请先选择或创建项目" />
        </Card>
      </Flex>
    )
  }

  if (packsQuery.isPending) return <LoadingBlock label="正在读取本批规则…" />
  if (packsQuery.error) return <ErrorBlock error={packsQuery.error} title="本批规则读取失败" />

  const activeProjectId = projectId

  function updateRule(index: number, next: ProjectRule) {
    setCandidateRules((current) => current.map((rule, ruleIndex) => (ruleIndex === index ? next : rule)))
    setPreviewResult(null)
  }

  async function analyze() {
    if (!instructions.trim()) return
    setBusy('analyze')
    setActionError(null)
    setNotice(null)
    try {
      const result = await analyzeProjectRules(activeProjectId, instructions)
      if (useAppStore.getState().currentProjectId !== activeProjectId) return
      setCandidateRules(result.rules)
      setPreviewResult(null)
      setNotice(`AI 已整理 ${result.rules.length} 条候选规则，请逐条确认。`)
    } catch (error) {
      setActionError(error)
    } finally {
      setBusy(null)
    }
  }

  async function preview() {
    if (!previewText.trim()) return
    setBusy('preview')
    setActionError(null)
    try {
      const result = await previewProjectRules(activeProjectId, {
        text: previewText,
        rules: candidateRules,
      })
      if (useAppStore.getState().currentProjectId !== activeProjectId) return
      setPreviewResult(result)
    } catch (error) {
      setActionError(error)
    } finally {
      setBusy(null)
    }
  }

  async function saveDraft() {
    setBusy('save')
    setActionError(null)
    try {
      const pack = await saveProjectRuleDraft(activeProjectId, candidateRules)
      if (useAppStore.getState().currentProjectId !== activeProjectId) return
      setLocalPacks((current) => [pack, ...current.filter((item) => item.revision !== pack.revision)])
      setNotice(`已保存修订 ${pack.revision}，尚未生效。`)
      void message.success('草稿已保存')
    } catch (error) {
      setActionError(error)
    } finally {
      setBusy(null)
    }
  }

  async function activate(revision: number) {
    setBusy(`activate:${revision}`)
    setActionError(null)
    try {
      const pack = await activateProjectRulePack(activeProjectId, revision)
      if (useAppStore.getState().currentProjectId !== activeProjectId) return
      setLocalPacks((current) =>
        current.map((item) =>
          item.revision === pack.revision
            ? pack
            : item.status === 'active'
              ? { ...item, status: 'draft' }
              : item,
        ),
      )
      setNotice(`修订 ${revision} 已激活，后续旁白与检索将按这批规则执行。`)
      void queryClient.invalidateQueries({ queryKey: ['project', projectId, 'rules'] })
      void message.success('规则已激活')
    } catch (error) {
      setActionError(error)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Flex vertical gap={20}>
      <PageHeader
        title="本批附加规则"
        description="创建项目后，先确认本批规则，再进入素材库。AI 只整理候选规则，确认并激活后生效。"
        extra={<Link to="/library"><Button>下一步：素材库</Button></Link>}
      />
      <Button disabled={busy !== null} onClick={async () => {
        setBusy('save')
        setActionError(null)
        try {
          const draft = await saveProjectRuleDraft(activeProjectId, [])
          await activateProjectRulePack(activeProjectId, draft.revision)
          await queryClient.invalidateQueries({ queryKey: ['project', projectId, 'rules'] })
          setNotice('已确认本项目不使用附加规则，可以进入素材库。')
        } catch (error) { setActionError(error) }
        finally { setBusy(null) }
      }}>本项目不使用附加规则</Button>

      {notice ? <Alert showIcon type="success" message={notice} closable onClose={() => setNotice(null)} /> : null}
      {actionError ? <ErrorBlock error={actionError} title="规则操作失败" /> : null}

      <Card title="1. AI 整理本批规则" variant="borderless">
        <Flex vertical gap={12}>
          <Input.TextArea
            aria-label="本批规则说明"
            rows={5}
            value={instructions}
            placeholder="例如：某品牌型号按指定读法朗读；某些词字幕保留但旁白不读；本批素材检索优先某类真实画面。"
            onChange={(event) => setInstructions(event.target.value)}
          />
          <div>
            <Button type="primary" loading={busy === 'analyze'} disabled={!instructions.trim()} onClick={() => void analyze()}>
              AI 分析规则
            </Button>
          </div>
        </Flex>
      </Card>

      <Card title="2. 候选规则确认" variant="borderless">
        {candidateRules.length ? (
          <Flex vertical gap={12}>
            {candidateRules.map((rule, index) => (
              <Card key={`${index}-${rule.kind}`} size="small" title={`规则 ${index + 1}`}>
                <Flex vertical gap={10}>
                  <Space wrap>
                    <Typography.Text>类型</Typography.Text>
                    <Select
                      aria-label={`规则 ${index + 1} 类型`}
                      value={rule.kind}
                      options={ruleKindOptions}
                      style={{ minWidth: 160 }}
                      onChange={(kind: RuleKind) => updateRule(index, normalizeRuleForKind(rule, kind))}
                    />
                    <Typography.Text>启用</Typography.Text>
                    <Switch
                      aria-label={`规则 ${index + 1} 启用`}
                      checked={rule.enabled}
                      onChange={(enabled) => updateRule(index, { ...rule, enabled })}
                    />
                  </Space>

                  {kindUsesMatch(rule.kind) ? (
                    <Input
                      aria-label={`规则 ${index + 1} 匹配内容`}
                      value={rule.match ?? ''}
                      placeholder="匹配内容"
                      onChange={(event) => updateRule(index, { ...rule, match: event.target.value })}
                    />
                  ) : null}

                  {kindUsesReplacement(rule.kind) ? (
                    <Input
                      aria-label={`规则 ${index + 1} 替换内容`}
                      value={rule.replacement ?? ''}
                      placeholder="替换或别名内容"
                      onChange={(event) => updateRule(index, { ...rule, replacement: event.target.value })}
                    />
                  ) : null}

                  {rule.kind === 'semantic_hint' ? (
                    <Input.TextArea
                      aria-label={`规则 ${index + 1} 语义提示`}
                      rows={2}
                      value={rule.hint ?? ''}
                      placeholder="描述本批检索希望优先匹配的真实画面语义"
                      onChange={(event) => updateRule(index, { ...rule, hint: event.target.value })}
                    />
                  ) : null}
                </Flex>
              </Card>
            ))}
          </Flex>
        ) : (
          <Empty description="先输入本批规则说明并点击“AI 分析规则”" />
        )}
      </Card>

      <Card title="3. 预览效果" variant="borderless">
        <Flex vertical gap={12}>
          <Input.TextArea
            aria-label="预览原文"
            rows={3}
            value={previewText}
            placeholder="粘贴一小段真实文案，检查朗读、字幕和检索文本是否符合预期。"
            onChange={(event) => setPreviewText(event.target.value)}
          />
          <div>
            <Button loading={busy === 'preview'} disabled={!previewText.trim()} onClick={() => void preview()}>
              预览效果
            </Button>
          </div>
          {previewResult ? (
            <Flex vertical gap={6}>
              <Typography.Text><strong>原文：</strong>{previewResult.canonical_text}</Typography.Text>
              <Typography.Text><strong>朗读：</strong>{previewResult.speech_text}</Typography.Text>
              <Typography.Text><strong>字幕：</strong>{previewResult.subtitle_text}</Typography.Text>
              <Typography.Text><strong>检索：</strong>{previewResult.retrieval_text}</Typography.Text>
              <Typography.Text>
                <strong>语义提示：</strong>{previewResult.semantic_hints.length ? previewResult.semantic_hints.join('；') : '无'}
              </Typography.Text>
            </Flex>
          ) : null}
        </Flex>
      </Card>

      <Card title="4. 保存并激活" variant="borderless">
        <Flex vertical gap={12}>
          <div>
            <Button type="primary" loading={busy === 'save'} disabled={!candidateRules.length} onClick={() => void saveDraft()}>
              保存草稿
            </Button>
          </div>

          {orderedPacks.length ? (
            <Flex vertical gap={8}>
              {orderedPacks.map((pack) => (
                <Flex key={pack.revision} align="center" justify="space-between" gap={12} wrap>
                  <Space wrap>
                    <Typography.Text>{packLabel(pack)}</Typography.Text>
                    <Tag>{`${pack.rules.length} 条规则`}</Tag>
                  </Space>
                  {pack.status === 'active' ? (
                    <Tag color="success">已生效</Tag>
                  ) : (
                    <Button
                      loading={busy === `activate:${pack.revision}`}
                      onClick={() => void activate(pack.revision)}
                    >
                      {`激活修订 ${pack.revision}`}
                    </Button>
                  )}
                </Flex>
              ))}
            </Flex>
          ) : (
            <Typography.Text type="secondary">还没有规则修订。保存草稿后，再明确选择激活。</Typography.Text>
          )}
        </Flex>
      </Card>
    </Flex>
  )
}
