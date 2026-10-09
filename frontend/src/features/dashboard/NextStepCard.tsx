import { ArrowRightOutlined } from '@ant-design/icons'
import { Button, Card, Flex, Typography } from 'antd'

export type NextStep = {
  label: string
  path: string | null
}

type NextStepCardProps = {
  step: NextStep
  onContinue: () => void
}

export function NextStepCard({ step, onContinue }: NextStepCardProps) {
  return (
    <Card variant="borderless">
      <Flex justify="space-between" align="center" gap={24} wrap>
        <div>
          <Typography.Text type="secondary">继续下一步</Typography.Text>
          <Typography.Title level={3} style={{ margin: '4px 0 0' }}>
            {step.label}
          </Typography.Title>
        </div>
        <Button type="primary" size="large" icon={<ArrowRightOutlined />} onClick={onContinue}>
          {step.label}
        </Button>
      </Flex>
    </Card>
  )
}
