import Papa from 'papaparse'

export const MAX_SOURCE_ROWS = 1000
export const MAX_SOURCE_FILE_BYTES = 2 * 1024 * 1024

export type SourceImportMode = 'exact' | string

export interface SourceDraft {
  id: string
  entryUrl: string
  mode: SourceImportMode
  name: string
  scopeHint: string
  origin: 'manual' | 'file'
  lineNumber: number
}

export type SourceFileErrorCode =
  | 'empty'
  | 'encoding'
  | 'missingUrlColumn'
  | 'parseFailed'
  | 'tooManyRows'
  | 'unsupportedFormat'

export class SourceFileError extends Error {
  readonly code: SourceFileErrorCode

  constructor(code: SourceFileErrorCode) {
    super(code)
    this.code = code
  }
}

const headerAliases = {
  entryUrl: ['entryurl', 'sourceurl', 'url', '网址', '入口网址'],
  mode: ['mode', '模式'],
  name: ['name', 'collectorname', 'sitename', '名称', '采集器名称', '网站名称'],
  scopeHint: ['scopehint', 'contentscope', '范围提示', '采集范围', '内容范围'],
} as const

function normalizedHeader(value: string) {
  return value.replace(/^\uFEFF/, '').trim().toLowerCase().replace(/[\s_-]+/g, '')
}

function fieldFor(fields: string[], aliases: readonly string[]) {
  return fields.find((field) => aliases.some((alias) => alias === field))
}

function exactDraft(
  entryUrl: string,
  lineNumber: number,
  index: number,
  values: { mode?: string; name?: string; scopeHint?: string } = {},
): SourceDraft {
  return {
    id: `file-${lineNumber}-${index}`,
    entryUrl: entryUrl.trim(),
    mode: values.mode?.trim().toLowerCase() || 'exact',
    name: values.name?.trim() || '',
    scopeHint: values.scopeHint?.trim() || '',
    origin: 'file',
    lineNumber,
  }
}

function parseCsv(text: string): SourceDraft[] {
  const parsed = Papa.parse<Record<string, string>>(text, {
    header: true,
    skipEmptyLines: 'greedy',
    transformHeader: normalizedHeader,
  })
  if (parsed.errors.some((error) => error.type === 'Quotes' || error.code === 'TooManyFields')) {
    throw new SourceFileError('parseFailed')
  }
  const fields = parsed.meta.fields ?? []
  const entryUrlField = fieldFor(fields, headerAliases.entryUrl)
  if (!entryUrlField) throw new SourceFileError('missingUrlColumn')
  const modeField = fieldFor(fields, headerAliases.mode)
  const nameField = fieldFor(fields, headerAliases.name)
  const scopeHintField = fieldFor(fields, headerAliases.scopeHint)
  const rows = parsed.data.map((row, index) => exactDraft(row[entryUrlField] ?? '', index + 2, index, {
    mode: modeField ? row[modeField] : undefined,
    name: nameField ? row[nameField] : undefined,
    scopeHint: scopeHintField ? row[scopeHintField] : undefined,
  }))
  if (rows.length > MAX_SOURCE_ROWS) throw new SourceFileError('tooManyRows')
  if (rows.length === 0) throw new SourceFileError('empty')
  return rows
}

function parseTxt(text: string): SourceDraft[] {
  const rows = text.split(/\r?\n/).map((value, index) => ({ value: value.trim(), lineNumber: index + 1 }))
    .filter(({ value }) => Boolean(value))
    .map(({ value, lineNumber }, index) => exactDraft(value, lineNumber, index))
  if (rows.length > MAX_SOURCE_ROWS) throw new SourceFileError('tooManyRows')
  if (rows.length === 0) throw new SourceFileError('empty')
  return rows
}

export function parseSourceFile(fileName: string, text: string): SourceDraft[] {
  if (text.includes('\uFFFD')) throw new SourceFileError('encoding')
  const extension = fileName.toLowerCase().split('.').pop()
  if (extension === 'csv') return parseCsv(text)
  if (extension === 'txt') return parseTxt(text.replace(/^\uFEFF/, ''))
  throw new SourceFileError('unsupportedFormat')
}

export function manualSourceDrafts(value: string): SourceDraft[] {
  return value.split(/\r?\n/).map((entryUrl, index) => ({ entryUrl: entryUrl.trim(), lineNumber: index + 1 }))
    .filter(({ entryUrl }) => Boolean(entryUrl))
    .map(({ entryUrl, lineNumber }, index) => ({
      id: `manual-${lineNumber}-${index}`,
      entryUrl,
      mode: 'exact',
      name: '',
      scopeHint: '',
      origin: 'manual',
      lineNumber,
    }))
}
