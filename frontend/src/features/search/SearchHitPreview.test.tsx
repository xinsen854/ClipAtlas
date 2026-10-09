import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { SearchHitPreview } from './SearchHitPreview'

it('reuses the cached scene image and requests source video only when opened',async()=>{
  const pause=vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{})
  const page=render(<SearchHitPreview videoId="v1" startMs={12000} endMs={17000}/>)
  expect(screen.getByAltText('命中片段所在场景的缓存画面')).toHaveAttribute('src','/api/v1/videos/v1/index-thumbnail?timestamp_ms=14500')
  expect(page.container.querySelector('video')).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'播放命中片段'}))
  const video=await screen.findByLabelText('命中片段视频') as HTMLVideoElement
  expect(video).toHaveAttribute('src','/api/v1/videos/v1/source-media#t=12,17')
  fireEvent.loadedMetadata(video)
  expect(video.currentTime).toBe(12)
  video.currentTime=17
  fireEvent.timeUpdate(video)
  expect(pause).toHaveBeenCalled()
  fireEvent.error(video)
  await waitFor(()=>expect(screen.getByText('无法播放原视频')).toBeInTheDocument())
  pause.mockRestore()
})
