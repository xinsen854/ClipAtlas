import type { ThemeConfig } from 'antd'

export const theme: ThemeConfig = {
  token: {
    colorPrimary: '#d97706',
    colorInfo: '#d97706',
    colorBgLayout: '#f8f4ef',
    colorText: '#26211d',
    colorBorderSecondary: '#eadfd6',
    borderRadius: 10,
    fontSize: 14,
  },
  components: {
    Menu: {
      itemSelectedBg: '#fff1dc',
      itemSelectedColor: '#b45309',
      itemHoverBg: '#fff7ed',
      itemHoverColor: '#9a4b08',
    },
    Button: {
      primaryShadow: 'none',
    },
  },
}
