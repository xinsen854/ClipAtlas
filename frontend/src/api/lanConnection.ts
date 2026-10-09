let prefix = ''

export function setLanPrefix(value: string) { prefix = value }
export function apiPath(path: string) { return prefix + path }
export function lanConnectionId() { return prefix.split('/')[2] || '' }
export function isLanConnection() { return !!lanConnectionId() }
