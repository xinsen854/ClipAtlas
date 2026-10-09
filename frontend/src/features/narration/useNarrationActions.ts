import { useMutation, useQueryClient } from '@tanstack/react-query'

import {
  activateNarrationTrack,
  createSpeechProfile,
  createTtsNarration,
  importNarration,
  randomizeSpeechProfile,
} from '../../api/speech'

export function useNarrationActions(projectId: string) {
  const queryClient = useQueryClient()
  const narrationKey = ['project', projectId, 'narrations'] as const
  const profileKey = ['project', projectId, 'speech-profiles'] as const

  const createProfile = useMutation({
    mutationFn: (input: Parameters<typeof createSpeechProfile>[0]) => createSpeechProfile(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: profileKey })
    },
  })

  const randomizeProfile = useMutation({
    mutationFn: (input: Parameters<typeof randomizeSpeechProfile>[0]) => randomizeSpeechProfile(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: profileKey })
    },
  })

  const createTts = useMutation({
    mutationFn: (input: Parameters<typeof createTtsNarration>[0]) => createTtsNarration(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: narrationKey })
      await queryClient.invalidateQueries({ queryKey: ['project', projectId, 'script'] })
    },
  })

  const importTrack = useMutation({
    mutationFn: (input: Parameters<typeof importNarration>[0]) => importNarration(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: narrationKey })
      await queryClient.invalidateQueries({ queryKey: ['project', projectId, 'script'] })
    },
  })

  const activateTrack = useMutation({
    mutationFn: (trackId: string) => activateNarrationTrack(trackId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: narrationKey })
      await queryClient.invalidateQueries({ queryKey: ['project', projectId, 'script'] })
    },
  })

  return {
    createProfile,
    randomizeProfile,
    createTts,
    importTrack,
    activateTrack,
  }
}
