import { ControlApiError, buildApiUrl } from '@/shared/api/httpClient';

export type SSEOpenPayload = {
  response: Response;
  runSessionId?: string;
};

export type SSEHandlers<TEvent> = {
  signal?: AbortSignal;
  onOpen?: (payload: SSEOpenPayload) => void;
  onEvent?: (eventName: string, payload: TEvent) => void;
  onClose?: () => void;
};

function parseEventChunk(chunk: string): { eventName: string; data: string } | null {
  const lines = chunk.replace(/\r/g, '').split('\n');
  let eventName = 'message';
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim();
      continue;
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  return {
    eventName,
    data: dataLines.join('\n'),
  };
}

export async function postSSE<TRequest, TEvent>(
  path: string,
  body: TRequest,
  handlers: SSEHandlers<TEvent>,
): Promise<void> {
  const response = await fetch(buildApiUrl(path), {
    method: 'POST',
    signal: handlers.signal,
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = (await response.json()) as { error?: string };
      message = payload.error ?? message;
    } catch {
      // Keep the HTTP status text fallback.
    }
    throw new ControlApiError(message, response.status);
  }

  const runSessionId = response.headers.get('X-Deepagents-Run-Session-ID') ?? undefined;
  handlers.onOpen?.({ response, runSessionId });

  const reader = response.body?.getReader();
  if (!reader) {
    handlers.onClose?.();
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    while (true) {
      const boundary = buffer.indexOf('\n\n');
      if (boundary < 0) {
        break;
      }

      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const parsed = parseEventChunk(chunk);
      if (!parsed) {
        continue;
      }

      handlers.onEvent?.(parsed.eventName, JSON.parse(parsed.data) as TEvent);
    }
  }

  handlers.onClose?.();
}

