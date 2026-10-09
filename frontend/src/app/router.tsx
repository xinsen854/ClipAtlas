import { createBrowserRouter } from 'react-router-dom'

import { AppShell } from '../components/AppShell'
import { SegmentAnnotationsPage } from '../features/annotation/SegmentAnnotationsPage'
import { AutoDirectorPage } from '../features/autoDirector/AutoDirectorPage'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { LibraryItemPage } from '../features/library/LibraryItemPage'
import { IndexResultsPage } from '../features/library/IndexResultsPage'
import { LibraryPage } from '../features/library/LibraryPage'
import { NarrationPage } from '../features/narration/NarrationPage'
import { BatchNarrationPage } from '../features/narration/BatchNarrationPage'
import { RoughCutPage } from '../features/roughcut/RoughCutPage'
import { RulesPage } from '../features/rules/RulesPage'
import { SearchPage } from '../features/search/SearchPage'
import { SettingsPage } from '../features/settings/SettingsPage'
import { FineCutMountPage } from '../integrations/finecut/FineCutMountPage'
import { HypitPage } from '../features/hypit/HypitPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'library', element: <LibraryPage /> },
      { path: 'library/items/:itemId', element: <LibraryItemPage /> },
      { path: 'library/items/:itemId/index-results', element: <IndexResultsPage /> },
      { path: 'library/items/:itemId/segments', element: <SegmentAnnotationsPage /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'narration', element: <NarrationPage /> },
      { path: 'narration/batch', element: <BatchNarrationPage /> },
      { path: 'auto-director', element: <AutoDirectorPage /> },
      { path: 'rules', element: <RulesPage /> },
      { path: 'rough-cut', element: <RoughCutPage /> },
      { path: 'rough-cut/:planId', element: <FineCutMountPage /> },
      { path: 'finecut/:planId', element: <FineCutMountPage /> },
      { path: 'hypit', element: <HypitPage /> },
      { path: 'settings', element: <SettingsPage /> },
    ],
  },
])
