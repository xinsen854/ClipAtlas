import { useState } from 'react'
import { Alert, Button, Flex, Modal, Typography } from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { apiPath, isLanConnection } from '../../api/lanConnection'
import { LocalMaterial } from '../../lan/LocalMaterial'

type Props = { videoId: string; startMs: number; endMs: number }

export function SearchHitPreview({ videoId, startMs, endMs }: Props) {
  const [open, setOpen] = useState(false)
  const [imageMissing, setImageMissing] = useState(false)
  const [videoError, setVideoError] = useState(false)
  const root = apiPath(`/api/v1/videos/${encodeURIComponent(videoId)}`)
  const thumbnail = `${root}/index-thumbnail?timestamp_ms=${Math.floor((startMs + endMs) / 2)}`

  return (
    <>
      {isLanConnection() ? <LocalMaterial videoId={videoId} startMs={startMs} endMs={endMs} /> : null}
      <Flex gap={12} align="center" wrap>
        {imageMissing ? (
          <Typography.Text type="secondary">暂无该场景的缓存缩略图</Typography.Text>
        ) : (
          <img src={thumbnail} alt="命中片段所在场景的缓存画面" loading="lazy"
            onError={() => setImageMissing(true)}
            style={{ width: 280, maxWidth: '100%', height: 158, objectFit: 'contain',
              background: '#171717', borderRadius: 8 }} />
        )}
        <Flex vertical gap={8}>
          <Button aria-label="播放命中片段" icon={<PlayCircleOutlined />} onClick={() => { setVideoError(false); setOpen(true) }}>
            播放命中片段
          </Button>
          <Typography.Text type="secondary">缩略图为所在场景的已有抽帧，播放可检查具体时间段。</Typography.Text>
        </Flex>
      </Flex>
      <Modal open={open} title="命中片段预览" footer={null} width={880}
        destroyOnHidden onCancel={() => setOpen(false)}>
        {open ? (
          <video controls autoPlay preload="metadata"
            aria-label="命中片段视频"
            src={`${root}/source-media#t=${startMs / 1000},${endMs / 1000}`}
            poster={imageMissing ? undefined : thumbnail}
            style={{ width: '100%', maxHeight: '65vh', background: '#000' }}
            onLoadedMetadata={(event) => { event.currentTarget.currentTime = startMs / 1000 }}
            onTimeUpdate={(event) => {
              if (event.currentTarget.currentTime >= endMs / 1000) event.currentTarget.pause()
            }}
            onPlay={(event) => {
              if (event.currentTarget.currentTime >= endMs / 1000) {
                event.currentTarget.currentTime = startMs / 1000
              }
            }}
            onError={() => setVideoError(true)} />
        ) : null}
        {videoError ? <Alert type="warning" showIcon message="无法播放原视频"
          description="请检查原文件是否仍在原位置；部分视频编码浏览器无法播放，可先查看缓存画面。" /> : null}
      </Modal>
    </>
  )
}
