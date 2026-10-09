import type { ReactNode } from 'react'
import { Flex, Typography } from 'antd'

const { Paragraph, Title } = Typography

type PageHeaderProps = {
  title: string
  description?: string
  extra?: ReactNode
}

export function PageHeader({ title, description, extra }: PageHeaderProps) {
  return (
    <Flex justify="space-between" align="flex-start" gap={24} wrap>
      <div>
        <Title level={2} style={{ marginBottom: description ? 4 : 0 }}>
          {title}
        </Title>
        {description ? (
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            {description}
          </Paragraph>
        ) : null}
      </div>
      {extra}
    </Flex>
  )
}
