export function runTimestamp(run: { startedAtIso?: string; startedAt: string }, locale: string) {
  if (!run.startedAtIso) return run.startedAt
  const date = new Date(run.startedAtIso)
  if (Number.isNaN(date.getTime())) return run.startedAt
  return new Intl.DateTimeFormat(locale === 'en' ? 'en-GB' : 'zh-CN', { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false }).format(date)
}

export function readableContent(content: string) {
  if (!/<\/?[a-z][^>]*>/i.test(content)) return { text: content, isHtml: false }
  // Parse inertly and render only text. Never insert source DOM or load its embedded resources.
  const template = document.createElement('template')
  template.innerHTML = content
  const fragment = template.content
  fragment.querySelectorAll('script,style,template,noscript,iframe,object,embed,button,input,select,[hidden],[aria-hidden="true"]').forEach(node => node.remove())
  fragment.querySelectorAll<HTMLElement>('[style]').forEach(node => {
    if (node.style.display === 'none' || node.style.visibility === 'hidden') node.remove()
  })
  fragment.querySelectorAll('br,p,div,h1,h2,h3,h4,h5,h6,li,tr,section,article').forEach(node => node.append(document.createTextNode('\n')))
  fragment.querySelectorAll('td,th').forEach(node => node.append(document.createTextNode('\t')))
  const text = (fragment.textContent ?? '').split('\n').map(line => line.trim()).filter(Boolean).join('\n')
  return { text, isHtml: true }
}
