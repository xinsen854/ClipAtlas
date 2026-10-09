import {
  DatabaseOutlined,
  ApiOutlined,
  FileTextOutlined,
  GithubOutlined,
  HomeOutlined,
  ProfileOutlined,
  RobotOutlined,
  SearchOutlined,
  ScissorOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Button, Layout, Menu, Space, Tag, Tooltip, Typography } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { getHealth } from '../api/health'
import { ProjectSwitcher } from './ProjectSwitcher'
import { useAppStore } from '../stores/useAppStore'
import { setLanguage, useLanguage } from '../language'

const { Content, Header, Sider } = Layout
const SIDEBAR_WIDTH = 216

const primaryItems = [
  { key: '/', icon: <HomeOutlined />, label: '工作台' },
  { key: '/rules', icon: <ProfileOutlined />, label: '本批规则' },
  { key: '/library', icon: <DatabaseOutlined />, label: '素材库' },
  { key: '/search', icon: <SearchOutlined />, label: '素材搜索' },
  { key: '/narration', icon: <FileTextOutlined />, label: '文案与旁白' },
  { key: '/auto-director', icon: <RobotOutlined />, label: '自动编导' },
  { key: '/rough-cut', icon: <ScissorOutlined />, label: '剪辑草稿' },
  { key: '/hypit', icon: <ApiOutlined />, label: 'Hypit' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
]

function selectedMenuKey(pathname: string): string {
  if (pathname.startsWith('/finecut/')) return '/rough-cut'

  for (const key of ['/library', '/search', '/narration', '/auto-director', '/rules', '/rough-cut', '/hypit', '/settings']) {
    if (pathname === key || pathname.startsWith(`${key}/`)) return key
  }
  return '/'
}

export function AppShell() {
  const language = useLanguage()
  const location = useLocation()
  const navigate = useNavigate()
  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    retry: false,
    refetchInterval: () => (document.visibilityState === 'visible' ? 30_000 : false),
  })
  const healthOk = healthQuery.isSuccess && healthQuery.data.status === 'ok'

  async function handleMenuClick(key: string): Promise<void> {
    await navigate(key)
  }

  return (
    <Layout style={{ height: '100vh', overflow: 'hidden', background: '#f8f4ef' }}>
      <Sider data-testid="app-sidebar" width={SIDEBAR_WIDTH} theme="light" style={{ position: 'fixed', insetInlineStart: 0, top: 0, bottom: 0, height: '100vh', borderRight: '1px solid #eadfd6', background: '#fffdf9' }}>
        <div style={{ padding: '22px 24px 18px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}><img src="/logo.png" alt="ClipAtlas" style={{ height: 28, width: 'auto', display: 'block' }} /></div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>AI 素材工作台</Typography.Text>
        </div>
        <Menu mode="inline" selectedKeys={[selectedMenuKey(location.pathname)]} items={primaryItems} onClick={({ key }) => void handleMenuClick(key)} style={{ borderInlineEnd: 0, background: 'transparent' }} />
        <div style={{ position: 'absolute', insetInline: 24, bottom: 18 }}>
          <Typography.Link aria-label="源代码" href="https://github.com/xinsen854/ClipAtlas" target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
            <GithubOutlined /> 源代码
          </Typography.Link>
        </div>
      </Sider>
      <Layout style={{ height: '100vh', minWidth: 0, marginInlineStart: SIDEBAR_WIDTH, background: '#f8f4ef' }}>
        <Header style={{ height: 64, flex: '0 0 64px', padding: '0 24px', background: '#fffdf9', borderBottom: '1px solid #eadfd6', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24 }}>
          <ProjectSwitcher />
          <Space>
            <Tooltip title={language === 'en' ? 'Switch to Chinese' : 'Switch to English'}>
              <Button size="small" onClick={() => setLanguage(language === 'en' ? 'zh' : 'en')}>
                {language === 'en' ? '中文' : 'EN'}
              </Button>
            </Tooltip>
            {healthQuery.isSuccess && healthQuery.data?.version ? <Tag>v{healthQuery.data.version}</Tag> : null}{healthQuery.isPending ? <Tag>服务检测中</Tag> : healthOk ? <Tag color="success">服务正常</Tag> : <Tag color="error">服务未连接</Tag>}
          </Space>
        </Header>
        <Content data-testid="app-content-scroll" style={{ padding: 24, overflow: 'auto', minHeight: 0 }}><Outlet /></Content>
      </Layout>
    </Layout>
  )
}
