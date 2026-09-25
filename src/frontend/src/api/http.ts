/**
 * The single place an HTTP request to the management API is made.
 *
 * Four entry points sit on one private `request()`: JSON, no-content, binary
 * download and multipart upload. Uploads use `XMLHttpRequest` rather than
 * `fetch` because only XHR reports upload progress, and the API accepts files
 * up to 100 MiB.
 */
import { env } from '@/app/env'
import { apiErrorFromBody, ApiError, networkError } from '@/api/errors'
import { tokenStore } from '@/api/token-store'

export interface RequestOptions {
  method?: string
  body?: unknown
  signal?: AbortSignal
  /**
   * Login and signup must not trigger the global logout: a 401 there means bad
   * credentials and belongs in the form, not in a session-expired redirect.
   */
  skipAuthRedirect?: boolean
}

type UnauthorizedHandler = () => void

let onUnauthorized: UnauthorizedHandler | null = null
let handlingUnauthorized = false

/** Registered once by `AuthProvider`. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler
}

function notifyUnauthorized(): void {
  if (!onUnauthorized || handlingUnauthorized) return
  // Several parallel requests can 401 together; one logout is enough.
  handlingUnauthorized = true
  try {
    onUnauthorized()
  } finally {
    // Release on the next tick so the burst collapses into a single handling.
    setTimeout(() => {
      handlingUnauthorized = false
    }, 0)
  }
}

export function resolveUrl(path: string): string {
  return new URL(path.replace(/^\//, ''), env.apiBaseUrl).toString()
}

function authHeaders(): Record<string, string> {
  const session = tokenStore.get()
  return session ? { Authorization: `Bearer ${session.accessToken}` } : {}
}

async function request(path: string, options: RequestOptions = {}): Promise<Response> {
  const { method = 'GET', body, signal, skipAuthRedirect } = options

  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...authHeaders(),
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(resolveUrl(path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw networkError(cause)
  }

  if (response.ok) return response

  if (response.status === 401 && !skipAuthRedirect) notifyUnauthorized()

  const raw = await response.text().catch(() => '')
  throw apiErrorFromBody(response.status, response.headers.get('content-type'), raw)
}

export async function apiJson<T>(path: string, options?: RequestOptions): Promise<T> {
  const response = await request(path, options)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function apiVoid(path: string, options?: RequestOptions): Promise<void> {
  await request(path, options)
}

export interface DownloadedBlob {
  blob: Blob
  fileName?: string
}

/**
 * Downloads binary content. The endpoint requires the bearer header, so a plain
 * anchor `href` cannot be used and the body has to be buffered as a blob.
 */
export async function apiBlob(
  path: string,
  options?: RequestOptions,
): Promise<DownloadedBlob> {
  const response = await request(path, options)
  const blob = await response.blob()
  return {
    blob,
    fileName: parseContentDispositionFileName(
      response.headers.get('content-disposition'),
    ),
  }
}

function parseContentDispositionFileName(header: string | null): string | undefined {
  if (!header) return undefined
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      // Fall through to the plain form below.
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain?.[1]
}

export interface UploadOptions {
  onProgress?: (fraction: number) => void
  signal?: AbortSignal
}

/**
 * Uploads one file as `multipart/form-data`.
 *
 * The form field name must be exactly `file`, matching the controller's
 * `IFormFile file` parameter. `Content-Type` is deliberately not set so the
 * browser generates the multipart boundary.
 */
export function apiUpload<T>(
  path: string,
  file: File,
  { onProgress, signal }: UploadOptions = {},
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const form = new FormData()
    form.append('file', file)

    xhr.open('POST', resolveUrl(path))
    xhr.responseType = 'text'

    const session = tokenStore.get()
    if (session) xhr.setRequestHeader('Authorization', `Bearer ${session.accessToken}`)
    xhr.setRequestHeader('Accept', 'application/json')

    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && event.total > 0) {
          onProgress(event.loaded / event.total)
        }
      }
    }

    const abort = () => xhr.abort()
    signal?.addEventListener('abort', abort)

    const cleanup = () => signal?.removeEventListener('abort', abort)

    xhr.onload = () => {
      cleanup()
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as T)
        } catch (cause) {
          reject(
            new ApiError({
              status: xhr.status,
              title: 'The server returned an unreadable response',
              detail: cause instanceof Error ? cause.message : undefined,
            }),
          )
        }
        return
      }

      if (xhr.status === 401) notifyUnauthorized()
      reject(
        apiErrorFromBody(
          xhr.status,
          xhr.getResponseHeader('content-type'),
          xhr.responseText ?? '',
        ),
      )
    }

    xhr.onerror = () => {
      cleanup()
      reject(networkError())
    }
    xhr.ontimeout = () => {
      cleanup()
      reject(networkError())
    }
    xhr.onabort = () => {
      cleanup()
      reject(new DOMException('Upload cancelled', 'AbortError'))
    }

    xhr.send(form)
  })
}
