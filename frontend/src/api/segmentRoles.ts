import { apiRequest } from './client'

export type SegmentFallbackRole = 'normal' | 'generic' | 'review_placeholder' | 'never'

export type SegmentFallbackRoleResponse = {
  segment_id: string
  role: SegmentFallbackRole
}

export function setSegmentFallbackRole(
  segmentId: string,
  role: SegmentFallbackRole,
): Promise<SegmentFallbackRoleResponse> {
  return apiRequest<SegmentFallbackRoleResponse>(
    `/api/v1/library/segments/${encodeURIComponent(segmentId)}/fallback-role`,
    { method: 'PATCH', body: JSON.stringify({ role }) },
  )
}
