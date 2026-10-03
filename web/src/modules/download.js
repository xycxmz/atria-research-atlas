/**
 * 浏览器下载辅助（S3 / V2-014）：把导出文件交给用户带走。
 */
export function safeName(s) {
  return String(s || 'all')
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/\s+/g, '-')
    .slice(0, 60)
}

export function downloadBlob(filename, blob) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

export function downloadText(filename, text, mime = 'text/plain') {
  downloadBlob(filename, new Blob([text], { type: mime + ';charset=utf-8' }))
}
