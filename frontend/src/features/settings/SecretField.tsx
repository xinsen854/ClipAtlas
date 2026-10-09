import { Button, Flex, Input, Space, Tag, Typography } from 'antd'

import type { SettingSource } from '../../api/settings'

const ENVIRONMENT_NOTICE = '当前值来自环境变量。'

function sourceLabel(source: SettingSource): string {
  if (source === 'environment') return '环境变量'
  if (source === 'file') return '本机配置'
  return '默认值'
}

type SecretFieldProps = {
  label: string
  configured: boolean
  source: SettingSource
  value: string
  clearPending: boolean
  onChange: (value: string) => void
  onClear: () => void
}

export function SecretField({
  label,
  configured,
  source,
  value,
  clearPending,
  onChange,
  onClear,
}: SecretFieldProps) {
  return (
    <Flex vertical gap={8}>
      <Flex align="center" justify="space-between" gap={12} wrap>
        <Typography.Text strong>{label}</Typography.Text>
        <Space size={6} wrap>
          <Tag color={configured ? 'success' : 'default'}>
            {configured ? '已配置' : '未配置'}
          </Tag>
          <Tag>{sourceLabel(source)}</Tag>
          {clearPending ? <Tag color="warning">保存后清除</Tag> : null}
        </Space>
      </Flex>
      <Input.Password
        aria-label={label}
        autoComplete="new-password"
        value={value}
        placeholder="留空表示不修改已保存密钥"
        onChange={(event) => onChange(event.target.value)}
      />
      {source === 'environment' ? (
        <Typography.Text type="warning">{ENVIRONMENT_NOTICE}</Typography.Text>
      ) : null}
      <div>
        <Button
          danger
          size="small"
          disabled={!configured && !clearPending}
          onClick={onClear}
        >
          清除已保存密钥
        </Button>
      </div>
    </Flex>
  )
}
