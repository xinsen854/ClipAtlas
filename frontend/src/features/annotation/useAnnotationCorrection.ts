import { useMutation, useQueryClient } from '@tanstack/react-query'

import {
  updateSegmentAnnotation,
  type UpdateAnnotationInput,
} from '../../api/library'

export type AnnotationCorrectionVariables = {
  segmentId: string
  input: UpdateAnnotationInput
}

export function useAnnotationCorrection(videoId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ segmentId, input }: AnnotationCorrectionVariables) =>
      updateSegmentAnnotation(segmentId, input),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['video', 'segments', videoId] }),
        queryClient.invalidateQueries({ queryKey: ['video', videoId] }),
      ])
    },
  })
}
