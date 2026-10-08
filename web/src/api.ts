/**
 * Thin wrapper around fetch.
 *
 * Relative URLs only — nginx serves this app and proxies /api to FastAPI, so
 * everything is one origin. The session cookie is sent automatically and is
 * HTTP-only, meaning this code never sees or handles a token.
 */

export class ApiError extends Error {
  readonly status: number;
  /** Seconds to wait, from the Retry-After header on a 429. */
  readonly retryAfter: number | null;

  constructor(
    status: number,
    message: string,
    retryAfter: number | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  // **JSON unless the body plainly is not.** Every call here sends a JSON
  // string, so declaring it by default is right — but a photo goes up as the
  // `File` itself, and labelling image bytes as JSON is a claim that happens to
  // be harmless here only because the server decodes the bytes to find out what
  // they are. Letting the browser set the type for a Blob is the honest answer.
  const sendsJson = init?.body === undefined || typeof init.body === 'string';

  const response = await fetch(path, {
    ...init,
    headers: {
      ...(sendsJson ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    // FastAPI puts its message in `detail`. Fall back to the status text when
    // the body isn't JSON — e.g. an nginx error page.
    const body = await response.json().catch(() => null);
    const retryAfter = Number(response.headers.get('Retry-After')) || null;

    // 422 is a validation error: `detail` is an array of per-field problems,
    // not a string. Rendering it raw would put "[object Object]" on screen.
    const detail = Array.isArray(body?.detail)
      ? (body.detail[0]?.msg ?? 'Please check the values you entered.')
      : body?.detail;

    throw new ApiError(
      response.status,
      detail ?? response.statusText ?? 'Request failed',
      retryAfter,
    );
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
