export function collectorDisplayName(name: string) {
  return name.replace(/\s*·\s*入口\s+\d+\s*$/, '')
}

export function sourceLocationLabel(sourceUrl: string, sourceHost: string) {
  try {
    const url = new URL(sourceUrl)
    const parts = url.pathname.split('/').filter(Boolean)
    if (parts.at(-1)?.match(/^index(?:\.[a-z0-9]+)?$/i)) parts.pop()
    const path = parts.slice(-2).join('/')
    return path ? `${sourceHost} / ${path}` : sourceHost
  } catch {
    return sourceHost
  }
}

export function collectorSourceLabel(collectorName: string, sourceHost: string) {
  const displayName = collectorDisplayName(collectorName).trim()
  return displayName.toLowerCase() === sourceHost.trim().toLowerCase() ? sourceHost : `${displayName} · ${sourceHost}`
}
