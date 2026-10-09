import { useMutation, useQueryClient } from '@tanstack/react-query'

import {
  addLibraryRoot,
  parseLibraryItem,
  pauseLibraryProcessing,
  reparseLibraryItem,
  resumeLibraryProcessing,
  retryLibraryItem,
  scanLibrary,
  supplementLibrary,
  type AddLibraryRootInput,
  type LibraryProcessingState,
} from '../../api/library'

export function useLibraryActions() {
  const queryClient = useQueryClient()

  const invalidateLibraryData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['library', 'items'] }),
      queryClient.invalidateQueries({ queryKey: ['library', 'summary'] }),
    ])
  }

  const addRootMutation = useMutation({
    mutationFn: (input: AddLibraryRootInput) => addLibraryRoot(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['library', 'roots'] })
    },
  })

  const scanMutation = useMutation({
    mutationFn: scanLibrary,
    onSuccess: invalidateLibraryData,
  })

  const parseMutation = useMutation({
    mutationFn: (itemId: string) => parseLibraryItem(itemId),
    onSuccess: invalidateLibraryData,
  })

  const reparseMutation = useMutation({
    mutationFn: (itemId: string) => reparseLibraryItem(itemId),
    onSuccess: invalidateLibraryData,
  })
  const retryMutation = useMutation({
    mutationFn: (itemId: string) => retryLibraryItem(itemId),
    onSuccess: invalidateLibraryData,
  })

  const updateProcessingState = (state: LibraryProcessingState) => {
    queryClient.setQueryData(['library', 'processing'], state)
  }

  const pauseProcessingMutation = useMutation({
    mutationFn: pauseLibraryProcessing,
    onSuccess: updateProcessingState,
  })

  const resumeProcessingMutation = useMutation({
    mutationFn: resumeLibraryProcessing,
    onSuccess: updateProcessingState,
  })

  const supplementMutation = useMutation({
    mutationFn: supplementLibrary,
    onSuccess: async () => {
      await invalidateLibraryData()
      await queryClient.invalidateQueries({ queryKey: ['library', 'processing'] })
    },
  })

  return {
    addRootMutation,
    scanMutation,
    parseMutation,
    reparseMutation,
    retryMutation,
    pauseProcessingMutation,
    resumeProcessingMutation,
    supplementMutation,
  }
}
