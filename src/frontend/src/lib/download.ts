/**
 * Saves an already-fetched blob to disk.
 *
 * The download endpoint needs an `Authorization` header, so the content has to
 * be fetched as a blob first; this only handles the save step.
 */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.rel = 'noopener'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  // Revoking synchronously cancels the download in Safari.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
