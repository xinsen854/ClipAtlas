import { Flex, Spin, Typography } from 'antd'

export function LoadingBlock({ label = '正在加载…' }: { label?: string }) {
  return (
    <Flex vertical align="center" gap={12} style={{ padding: '48px 24px' }}>
      <Spin />
      <Typography.Text type="secondary">{label}</Typography.Text>
    </Flex>
  )
}
