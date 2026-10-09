import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import * as api from '../../api/library'
import { CacheLocationCard } from './CacheLocationCard'

vi.mock('../../api/library',()=>({getCacheLocation:vi.fn(),moveCacheLocation:vi.fn()}))

it('shows migration scope and requires explicit confirmation before moving cache',async()=>{
  vi.mocked(api.getCacheLocation).mockResolvedValue({path:'D:/cache',restart_required:false,environment_managed:false})
  vi.mocked(api.moveCacheLocation).mockResolvedValue({path:'B:/cache',previous_path:'D:/cache',files_moved:2,restart_required:true,backup_path:'D:/backup',warning:null})
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><CacheLocationCard/></QueryClientProvider>)
  await waitFor(()=>expect(screen.getByRole('textbox',{name:'素材缓存目录'})).toHaveValue('D:/cache'))
  fireEvent.change(screen.getByRole('textbox',{name:'素材缓存目录'}),{target:{value:'B:/cache'}})
  fireEvent.click(screen.getByRole('button',{name:'迁移到此目录'}))
  expect(api.moveCacheLocation).not.toHaveBeenCalled()
  expect(screen.getByText(/不会移动原始视频或重新解析素材/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'确认迁移'}))
  await waitFor(()=>expect(api.moveCacheLocation).toHaveBeenCalledWith('B:/cache',expect.anything()))
  await screen.findByText('缓存目录已迁移，请重启 ClipAtlas 后继续操作。')
  expect(screen.getByRole('button',{name:'迁移到此目录'})).toBeDisabled()
})
