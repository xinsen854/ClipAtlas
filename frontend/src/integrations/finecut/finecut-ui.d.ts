declare module '@finecut-ui' {
  export const fineCutUiAvailable: boolean
  export function mountFineCut(
    root: HTMLElement,
    options: { planId: string },
  ): () => void
}
