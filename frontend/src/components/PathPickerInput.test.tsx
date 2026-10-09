import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { PathPickerInput } from './PathPickerInput'
import * as systemApi from '../api/system'

vi.mock('../api/system', () => ({
  pickDirectory: vi.fn(),
  pickFile: vi.fn(),
}))

function renderPicker(props: Parameters<typeof PathPickerInput>[0]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <PathPickerInput {...props} />
    </QueryClientProvider>,
  )
}

describe('PathPickerInput', () => {
  beforeEach(() => {
    vi.mocked(systemApi.pickDirectory).mockReset()
    vi.mocked(systemApi.pickFile).mockReset()
  })

  it('renders the input value and a 选择 button', () => {
    renderPicker({ value: 'D:/素材', picker: 'directory' })
    expect(screen.getByRole('textbox')).toHaveValue('D:/素材')
    expect(screen.getByRole('button', { name: '选择文件夹' })).toBeInTheDocument()
  })

  it('picks a directory and writes it back through onChange', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    vi.mocked(systemApi.pickDirectory).mockResolvedValue('E:/JianyingPro Drafts')
    renderPicker({ value: '', onChange, picker: 'directory' })
    await user.click(screen.getByRole('button', { name: '选择文件夹' }))
    expect(onChange).toHaveBeenCalledWith('E:/JianyingPro Drafts')
  })

  it('does not write back when the user cancels the dialog', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    vi.mocked(systemApi.pickDirectory).mockResolvedValue(null)
    renderPicker({ value: '', onChange, picker: 'directory' })
    await user.click(screen.getByRole('button', { name: '选择文件夹' }))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('uses the file picker for picker=file', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    vi.mocked(systemApi.pickFile).mockResolvedValue('D:/JianyingPro/JianyingPro.exe')
    renderPicker({ value: '', onChange, picker: 'file' })
    await user.click(screen.getByRole('button', { name: '选择文件' }))
    expect(onChange).toHaveBeenCalledWith('D:/JianyingPro/JianyingPro.exe')
  })

  it('still allows typing a path manually', () => {
    const onChange = vi.fn()
    renderPicker({ value: '', onChange })
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'C:/素材' } })
    expect(onChange).toHaveBeenCalledWith('C:/素材')
  })
})
