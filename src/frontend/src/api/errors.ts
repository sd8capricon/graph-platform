/**
 * Error model for the management API.
 *
 * The API emits three distinct failure shapes and the client must not assume
 * JSON: `Forbid()` and the JWT middleware return **403/401 with an empty body**,
 * explicit failures return RFC 7807 `ProblemDetails`, and model validation
 * returns `ValidationProblemDetails` (identified by its `errors` dictionary).
 */

export interface ProblemDetailsBody {
  type?: string
  title?: string
  status?: number
  detail?: string
  instance?: string
  traceId?: string
  errors?: Record<string, string[]>
}

export interface ApiErrorInit {
  status: number
  title: string
  detail?: string
  errors?: Record<string, string[]>
  traceId?: string
}

/**
 * Written longhand rather than with constructor parameter properties, which
 * `erasableSyntaxOnly` forbids.
 */
export class ApiError extends Error {
  readonly status: number
  readonly title: string
  readonly detail?: string
  readonly errors?: Record<string, string[]>
  readonly traceId?: string

  constructor(init: ApiErrorInit) {
    super(init.detail ?? init.title)
    this.name = 'ApiError'
    this.status = init.status
    this.title = init.title
    this.detail = init.detail
    this.errors = init.errors
    this.traceId = init.traceId
  }

  /** A validation failure carries per-field messages; other failures do not. */
  get isValidation(): boolean {
    return this.errors !== undefined && Object.keys(this.errors).length > 0
  }

  /** `0` means the request never reached the server (offline, DNS, CORS). */
  get isNetwork(): boolean {
    return this.status === 0
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

/** Fallback titles, used when the response carries no body to read one from. */
export function defaultTitleForStatus(status: number): string {
  switch (status) {
    case 0:
      return 'Cannot reach the server'
    case 400:
      return 'Invalid request'
    case 401:
      return 'Your session has expired'
    case 403:
      return 'You do not have permission to do this'
    case 404:
      return 'Not found'
    case 409:
      return 'Conflict'
    case 413:
      return 'That file is too large'
    case 415:
      return 'Unsupported content type'
    default:
      return status >= 500 ? 'Something went wrong on the server' : 'Request failed'
  }
}

/** Builds an `ApiError` from a body that may be problem JSON, text, or nothing. */
export function apiErrorFromBody(
  status: number,
  contentType: string | null,
  rawBody: string,
): ApiError {
  const body = rawBody.trim()

  if (body && contentType && contentType.includes('json')) {
    try {
      const problem = JSON.parse(body) as ProblemDetailsBody
      return new ApiError({
        status,
        title: problem.title?.trim() || defaultTitleForStatus(status),
        detail: problem.detail?.trim() || undefined,
        errors: problem.errors,
        traceId: problem.traceId,
      })
    } catch {
      // Fall through to the plain-text handling below.
    }
  }

  return new ApiError({
    status,
    title: defaultTitleForStatus(status),
    // A proxy or the dev exception page can return HTML; keep a usable excerpt.
    detail: body ? body.slice(0, 500) : undefined,
  })
}

export function networkError(cause?: unknown): ApiError {
  return new ApiError({
    status: 0,
    title: defaultTitleForStatus(0),
    detail:
      cause instanceof Error && cause.message
        ? cause.message
        : 'Check your connection and that the API is running.',
  })
}

/** Form-level key used when a server message has no field to attach to. */
export const ROOT_ERROR_KEY = 'root.serverError'

/**
 * Normalises the API's validation keys to the client's field names.
 *
 * The API mixes conventions: `IValidatableObject` results use `nameof(ApiKey)`
 * and so are PascalCase, model-bound failures are camelCase, body-parse
 * failures key on `"$"`, and upload failures key on `"file"`. Each key is
 * emitted verbatim *and* camelCased so a caller can look up either, with
 * unattributable messages collected under `ROOT_ERROR_KEY`.
 */
export function getFieldErrors(error: ApiError): Record<string, string[]> {
  const mapped: Record<string, string[]> = {}
  if (!error.errors) return mapped

  const push = (key: string, messages: string[]) => {
    mapped[key] = [...(mapped[key] ?? []), ...messages]
  }

  for (const [key, messages] of Object.entries(error.errors)) {
    if (!messages?.length) continue

    if (key === '$' || key === '' || key.startsWith('$.')) {
      push(ROOT_ERROR_KEY, messages)
      continue
    }

    push(key, messages)
    const camel = key.charAt(0).toLowerCase() + key.slice(1)
    if (camel !== key) push(camel, messages)
  }

  return mapped
}

/** Flattens every validation message into one list, for a form-level summary. */
export function allErrorMessages(error: ApiError): string[] {
  if (!error.errors) return []
  return Object.values(error.errors).flat()
}
