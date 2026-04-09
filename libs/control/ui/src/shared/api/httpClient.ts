import type { ApiErrorResponse } from '@/shared/types/api';

export class ControlApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ControlApiError';
    this.status = status;
  }
}

const baseUrl = (() => {
  const value = import.meta.env.VITE_CONTROL_API_BASE_URL?.trim();
  if (!value) {
    return window.location.origin;
  }
  return value.replace(/\/$/, '');
})();

export function buildApiUrl(path: string, query?: Record<string, string | number | undefined>): string {
  const url = new URL(path, `${baseUrl}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === '') {
        continue;
      }
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function parseJsonSafe<T>(response: Response): Promise<T | null> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    return null;
  }
  return (await response.json()) as T;
}

async function request<TResponse>(
  method: 'GET' | 'PUT' | 'POST' | 'DELETE',
  path: string,
  options: {
    body?: unknown;
    query?: Record<string, string | number | undefined>;
    signal?: AbortSignal;
    responseType?: 'json' | 'blob';
  } = {},
): Promise<TResponse> {
  const expectsBlob = options.responseType === 'blob';
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const response = await fetch(buildApiUrl(path, options.query), {
    method,
    signal: options.signal,
    headers: {
      Accept: expectsBlob ? 'application/zip, application/octet-stream, */*' : 'application/json',
      ...(!isFormData && options.body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: isFormData ? options.body as FormData : options.body ? JSON.stringify(options.body) : undefined,
  });

  if (response.status === 204) {
    return undefined as TResponse;
  }

  if (!response.ok) {
    const errorBody = await parseJsonSafe<ApiErrorResponse>(response);
    throw new ControlApiError(errorBody?.error ?? response.statusText, response.status);
  }

  if (expectsBlob) {
    return (await response.blob()) as TResponse;
  }

  const payload = await parseJsonSafe<TResponse>(response);
  if (payload === null) {
    return undefined as TResponse;
  }
  return payload;
}

export const httpClient = {
  get<TResponse>(path: string, query?: Record<string, string | number | undefined>, signal?: AbortSignal) {
    return request<TResponse>('GET', path, { query, signal });
  },
  put<TRequest, TResponse>(path: string, body: TRequest, signal?: AbortSignal) {
    return request<TResponse>('PUT', path, { body, signal });
  },
  post<TRequest, TResponse>(
    path: string,
    body: TRequest,
    query?: Record<string, string | number | undefined>,
    signal?: AbortSignal,
  ) {
    return request<TResponse>('POST', path, { body, query, signal });
  },
  delete<TResponse>(path: string, query?: Record<string, string | number | undefined>, signal?: AbortSignal) {
    return request<TResponse>('DELETE', path, { query, signal });
  },
  postForm<TResponse>(path: string, body: FormData, signal?: AbortSignal) {
    return request<TResponse>('POST', path, { body, signal });
  },
  postBlob<TRequest>(path: string, body: TRequest, signal?: AbortSignal) {
    return request<Blob>('POST', path, { body, signal, responseType: 'blob' });
  },
  putForm<TResponse>(path: string, body: FormData, signal?: AbortSignal) {
    return request<TResponse>('PUT', path, { body, signal });
  },
  getBlob(path: string, query?: Record<string, string | number | undefined>, signal?: AbortSignal) {
    return request<Blob>('GET', path, { query, signal, responseType: 'blob' });
  },
};
