import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import * as api from '../../api/projects'
import { useAppStore } from '../../stores/useAppStore'
import { DeleteProjectButton } from './DeleteProjectButton'

vi.mock('../../api/projects', () => ({ getProjectDeletionPreview: vi.fn(), deleteProject: vi.fn() }))
const project={ id:'a', name:'二创', description:null, created_at:'now', updated_at:'now' }
const other={ ...project, id:'b', name:'其他项目' }

beforeEach(() => { vi.clearAllMocks(); useAppStore.setState({ currentProjectId:'a' }) })

it('previews ownership, requires confirmation, and selects a surviving project', async () => {
  const preview={project_id:'a',name:'二创',narrations:1,plans:2,batches:0,directories:['D:/audio/a'],warnings:[]}
  vi.mocked(api.getProjectDeletionPreview).mockResolvedValue(preview)
  vi.mocked(api.deleteProject).mockResolvedValue({...preview,backup_directory:'D:/backup'})
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
  client.setQueryData(['projects'],[project,other])
  render(<App><QueryClientProvider client={client}><MemoryRouter>
    <DeleteProjectButton project={project}/>
  </MemoryRouter></QueryClientProvider></App>)
  fireEvent.click(screen.getByRole('button',{name:'删除此项目'}))
  await screen.findByText('D:/audio/a')
  expect(screen.getByText(/全局素材库、Visual/)).toBeInTheDocument()
  expect(api.deleteProject).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button',{name:'确认删除此项目'}))
  await waitFor(() => expect(api.deleteProject).toHaveBeenCalledWith('a',expect.anything()))
  await waitFor(() => expect(useAppStore.getState().currentProjectId).toBe('b'))
  expect(client.getQueryData(['projects'])).toEqual([other])
})
