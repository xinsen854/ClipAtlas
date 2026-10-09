import { QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp, ConfigProvider } from 'antd'
import enUS from 'antd/locale/en_US'
import zhCN from 'antd/locale/zh_CN'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './app/App'
import { queryClient } from './app/queryClient'
import { theme } from './app/theme'
import { UiTranslator } from './i18n'
import { useLanguage } from './language'

const root = document.getElementById('root')

if (!root) {
  throw new Error('Missing #root element')
}

function Root() {
  const language = useLanguage()
  return (
    <StrictMode>
      <ConfigProvider locale={language === 'en' ? enUS : zhCN} theme={theme}>
        <AntdApp>
          <UiTranslator />
          <QueryClientProvider client={queryClient}>
            <App />
          </QueryClientProvider>
        </AntdApp>
      </ConfigProvider>
    </StrictMode>
  )
}

createRoot(root).render(<Root />)
