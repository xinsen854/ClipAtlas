export function readableSourcePath(uri: string): string {
  let decoded = uri
  try { decoded = decodeURIComponent(uri) } catch { /* Preserve malformed legacy paths. */ }
  if (/^file:\/\/(?:localhost)?\/[a-z]:\//i.test(decoded)) {
    return decoded.replace(/^file:\/\/(?:localhost)?\//i, '').replaceAll('/', '\\')
  }
  return decoded
}
