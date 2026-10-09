import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type AppState = {
  currentProjectId: string | null
  setCurrentProjectId: (id: string | null) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      currentProjectId: null,
      setCurrentProjectId: (id) => set({ currentProjectId: id }),
    }),
    {
      name: 'clipatlas.app.v0.1',
      partialize: (state) => ({ currentProjectId: state.currentProjectId }),
    },
  ),
)
