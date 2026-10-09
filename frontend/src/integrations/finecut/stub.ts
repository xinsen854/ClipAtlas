export const fineCutUiAvailable = false

export function mountFineCut(root: HTMLElement, _options: { planId: string }): () => void {
  root.replaceChildren()
  return () => root.replaceChildren()
}
