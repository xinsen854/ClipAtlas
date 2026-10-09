import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'

import * as api from '../../api/narrationBatches'
import type { NarrationTrackResponse } from '../../api/speech'
import type { RoughCutPlan } from '../../api/roughCut'
import { useAppStore } from '../../stores/useAppStore'
import { BatchNarrationPage } from './BatchNarrationPage'

vi.mock('../../api/narrationBatches', () => ({
  previewNarrationBatch: vi.fn(), createNarrationBatch: vi.fn(), listNarrationBatches: vi.fn(),
  getNarrationBatch: vi.fn(), importBatchAudio: vi.fn(), generateBatchPlan: vi.fn(),
}))

const scripts = [
  { id: 'entry-001', code: '001', title: '001 甲标题', text: '甲的独立文案' },
  { id: 'entry-002', code: '002', title: '002 乙标题', text: '乙的独立文案' },
]
let saved: api.NarrationBatch

beforeEach(() => {
  vi.clearAllMocks()
  useAppStore.setState({ currentProjectId: 'project-1' })
  saved = {
    id: 'batch-1', project_id: 'project-1', name: '测试合集', top_k: 12,
    created_at: '2026-09-06T00:00:00Z', updated_at: '2026-09-06T00:00:00Z',
    entries: scripts.map((script, i) => ({ ...script, audio_name: i === 0 ? '001.wav' : '002.wav',
      audio_size: i === 0 ? 1 : 2, narration_track_id: null, duration_ms: null, plan_id: null, last_error: null })),
  }
  vi.mocked(api.listNarrationBatches).mockResolvedValue([])
  vi.mocked(api.previewNarrationBatch).mockResolvedValue(scripts.map((script, i) => ({ script, audio_index: 1 - i, reason: '编号匹配', candidates: [1 - i] })))
  vi.mocked(api.createNarrationBatch).mockImplementation(async () => saved)
  vi.mocked(api.getNarrationBatch).mockImplementation(async () => saved)
  vi.mocked(api.importBatchAudio).mockImplementation(async (_project, _batch, entryId) => {
    saved = { ...saved, entries: saved.entries.map((entry) => entry.id === entryId ? { ...entry, narration_track_id: `track-${entryId}`, duration_ms: 1000 } : entry) }
    return {} as NarrationTrackResponse
  })
  vi.mocked(api.generateBatchPlan).mockImplementation(async (_project, _batch, entryId) => {
    saved = { ...saved, entries: saved.entries.map((entry) => entry.id === entryId ? { ...entry, plan_id: `plan-${entryId}` } : entry) }
    return {} as RoughCutPlan
  })
})

function page() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><BatchNarrationPage /></MemoryRouter>
  </QueryClientProvider>)
}

async function selectFiles() {
  const md = new File(['content'], '测试合集.md', { type: 'text/markdown' })
  Object.defineProperty(md, 'text', { value: async () => '## 001 甲标题\n甲的独立文案\n## 002 乙标题\n乙的独立文案' })
  fireEvent.change(screen.getByLabelText('批量MD文案'), { target: { files: [md] } })
  const fileInputs = document.querySelectorAll<HTMLInputElement>('input[type="file"]')
  const audioInput = Array.from(fileInputs).find((input) => input.accept?.startsWith('audio'))
  if (!audioInput) throw new Error('未找到音频上传输入框')
  fireEvent.change(audioInput, { target: { files: [new File(['bb'], '002.wav'), new File(['a'], '001.wav')] } })
  await screen.findByDisplayValue('测试合集')
  fireEvent.click(screen.getByRole('button', { name: '拆分并预览匹配' }))
  await screen.findByText('001 甲标题')
}

it('previews before upload, then imports each matching file and separately confirms serial planning', async () => {
  const user = userEvent.setup()
  page()
  await selectFiles()
  expect(api.importBatchAudio).not.toHaveBeenCalled()
  expect(api.generateBatchPlan).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '确认配对并批量导入旁白' }))
  expect(api.createNarrationBatch).not.toHaveBeenCalled()
  await user.click(await screen.findByRole('button', { name: '确认并导入' }, { timeout: 10_000 }))
  await waitFor(() => expect(api.createNarrationBatch).toHaveBeenCalledTimes(1), { timeout: 10_000 })
  await waitFor(() => expect(api.importBatchAudio).toHaveBeenCalledTimes(2), { timeout: 10_000 })
  await screen.findByText(/本轮完成：成功 2 条/, {}, { timeout: 10_000 })
  expect(vi.mocked(api.createNarrationBatch).mock.calls[0][1].assignments).toEqual([
    { entry_id: 'entry-001', audio_index: 1 }, { entry_id: 'entry-002', audio_index: 0 },
  ])
  expect(vi.mocked(api.importBatchAudio).mock.calls.map((call) => [call[2], call[3].name])).toEqual([
    ['entry-001', '001.wav'], ['entry-002', '002.wav'],
  ])
  expect(api.generateBatchPlan).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '串行生成就绪条目的粗剪' }))
  await user.click(await screen.findByRole('button', { name: '确认并生成' }, { timeout: 10_000 }))
  await waitFor(() => expect(api.generateBatchPlan).toHaveBeenCalledTimes(2), { timeout: 10_000 })
  await waitFor(() => expect(screen.getAllByRole('link', { name: '查看粗剪与导出' })).toHaveLength(2))
  expect(vi.mocked(api.generateBatchPlan).mock.calls.map((call) => call[2])).toEqual(['entry-001', 'entry-002'])
  expect(screen.getByRole('button', { name: '串行生成就绪条目的粗剪' })).toBeDisabled()
}, 60000)

it('does not import when matches are missing or reuse one audio', async () => {
  vi.mocked(api.previewNarrationBatch).mockResolvedValue(scripts.map((script) => ({ script, audio_index: 0, reason: '需核对', candidates: [0] })))
  page()
  await selectFiles()
  expect(screen.getByRole('button', { name: '确认配对并批量导入旁白' })).toBeDisabled()
  expect(api.createNarrationBatch).not.toHaveBeenCalled()
  expect(api.importBatchAudio).not.toHaveBeenCalled()
}, 20000)

it('allows checking three numbered scripts before selecting any narration files', async () => {
  const markdown='1. 标题甲\n正文甲。\n2. 标题乙\n正文乙。\n3. 标题与正文同一行，内容完整保留。'
  vi.mocked(api.previewNarrationBatch).mockResolvedValue([1,2,3].map(i => ({
    script:{id:`entry-00${i}`,code:`00${i}`,title:`${i}. 标题`,text:`正文${i}`},
    audio_index:null,reason:'未匹配，需手选',candidates:[],
  })))
  page()
  expect(screen.getByText(/顶层“1\. \/ 2\. \/ 3\.”/)).toBeInTheDocument()
  const md=new File([markdown],'三条.md',{type:'text/markdown'})
  Object.defineProperty(md,'text',{value:async()=>markdown})
  fireEvent.change(screen.getByLabelText('批量MD文案'),{target:{files:[md]}})
  await screen.findByDisplayValue('三条')
  fireEvent.click(screen.getByRole('button',{name:'拆分并预览匹配'}))
  await screen.findByText(/识别到 3 条文案，0 个旁白/)
  expect(api.previewNarrationBatch).toHaveBeenCalledWith('project-1',markdown,[])
  expect(api.createNarrationBatch).not.toHaveBeenCalled()
  expect(api.importBatchAudio).not.toHaveBeenCalled()
},20000)
