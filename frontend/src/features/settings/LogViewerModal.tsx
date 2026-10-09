import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Flex, Modal, Radio, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'

import { getLogs } from '../../api/system'
import { ErrorBlock } from '../../components/ErrorBlock'

const LEVEL_COLOR: Record<string, string> = {
  ERROR: 'red',
  WARN: 'orange',
  INFO: 'default',
}

export function LogViewerModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [onlyImportant, setOnlyImportant] = useState(true)
  const [lines, setLines] = useState(300)

  const logsQuery = useQuery({
    queryKey: ['system', 'logs', lines],
    queryFn: () => getLogs(lines),
    enabled: open,
    refetchInterval: 5000,
  })

  const visibleLines = useMemo(() => {
    const all = logsQuery.data?.lines ?? []
    return onlyImportant ? all.filter((line) => line.important) : all
  }, [logsQuery.data, onlyImportant])

  return (
    <Modal
      open={open}
      title="运行日志"
      width={880}
      onCancel={onClose}
      footer={null}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Flex justify="space-between" align="center" gap={8} wrap>
          <Space wrap>
            <Radio.Group
              value={onlyImportant}
              onChange={(event) => setOnlyImportant(event.target.value === true)}
              optionType="button"
              size="small"
              options={[
                { label: '只看重要信息（错误/警告）', value: true },
                { label: '全部', value: false },
              ]}
            />
            <Radio.Group
              value={lines}
              onChange={(event) => setLines(Number(event.target.value))}
              optionType="button"
              size="small"
              options={[
                { label: '最近 100 行', value: 100 },
                { label: '最近 300 行', value: 300 },
                { label: '最近 1000 行', value: 1000 },
              ]}
            />
          </Space>
          <Button size="small" loading={logsQuery.isFetching} onClick={() => void logsQuery.refetch()}>
            刷新
          </Button>
        </Flex>

        {logsQuery.error ? <ErrorBlock error={logsQuery.error} title="读取日志失败" /> : null}
        {logsQuery.data?.path ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            日志文件：{logsQuery.data.path}
          </Typography.Text>
        ) : (
          <Alert type="info" showIcon message="尚未生成日志文件。软件启动后会写入 data/logs/app.log。" />
        )}

        <Flex vertical gap={2} style={{ maxHeight: 420, overflow: 'auto', fontFamily: 'Consolas, monospace', fontSize: 12 }}>
          {visibleLines.length === 0 ? (
            <Typography.Text type="secondary">没有可显示的日志行。</Typography.Text>
          ) : (
            visibleLines.map((line, index) => (
              <Flex key={`${index}-${line.level}`} gap={6} align="baseline">
                <Tag color={LEVEL_COLOR[line.level] ?? 'default'} style={{ marginInlineEnd: 0, flexShrink: 0, width: 52, textAlign: 'center' }}>
                  {line.level}
                </Tag>
                <Typography.Text style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                  {line.text}
                </Typography.Text>
              </Flex>
            ))
          )}
        </Flex>
      </Space>
    </Modal>
  )
}
