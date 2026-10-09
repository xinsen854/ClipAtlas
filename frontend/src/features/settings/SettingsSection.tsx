import type { CSSProperties, ReactNode } from 'react'
import { Card, Flex, Typography } from 'antd'

export type SettingsSectionTone = 'bailian' | 'video' | 'embedding' | 'speech' | 'jianying'

type SettingsSectionProps = {
  title: string
  description?: string
  tone: SettingsSectionTone
  children: ReactNode
}

const toneStyles: Record<SettingsSectionTone, CSSProperties> = {
  bailian: {
    background: '#f7f3ff',
    borderColor: '#ded4ee',
  },
  video: {
    background: '#fff7ed',
    borderColor: '#f3d5b5',
  },
  embedding: {
    background: '#f7f3ff',
    borderColor: '#ded4ee',
  },
  speech: {
    background: '#eff8f7',
    borderColor: '#cfe3df',
  },
  jianying: {
    background: '#f6f2ed',
    borderColor: '#e3d9cf',
  },
}

export function SettingsSection({ title, description, tone, children }: SettingsSectionProps) {
  return (
    <Card
      data-testid={`settings-section-${tone}`}
      variant="outlined"
      title={title}
      style={toneStyles[tone]}
    >
      <Flex vertical gap={16}>
        {description ? (
          <Typography.Text type="secondary">{description}</Typography.Text>
        ) : null}
        {children}
      </Flex>
    </Card>
  )
}
