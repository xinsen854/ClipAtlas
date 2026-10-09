import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { App } from './App'

vi.mock('../api/projects', () => ({
  listProjects: vi.fn().mockResolvedValue([]),
  createProject: vi.fn(),
  updateProject: vi.fn(),
}))

vi.mock('../api/health', () => ({
  getHealth: vi.fn().mockResolvedValue({ status: 'ok', service: 'clipatlas', version: '0.1.0' }),
}))

test('renders ClipAtlas application name', () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )

  expect(screen.getByAltText('ClipAtlas')).toBeInTheDocument()
})
