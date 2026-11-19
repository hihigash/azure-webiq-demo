import type { RunEvent } from './types';

export function parseSseBlock(block: string): RunEvent | null {
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).replace(/^ /, ''))
    .join('\n');

  if (!data) return null;
  const value: unknown = JSON.parse(data);
  if (!value || typeof value !== 'object') throw new Error('不正なSSEイベントです');
  const event = value as Partial<RunEvent>;
  if (
    !['progress', 'result', 'error', 'done'].includes(event.event ?? '') ||
    !['A', 'B', 'C'].includes(event.columnId ?? '') ||
    typeof event.elapsedMs !== 'number' ||
    typeof event.sequence !== 'number'
  ) {
    throw new Error('SSEイベントの形式が不正です');
  }
  return event as RunEvent;
}

export async function consumeSse(
  response: Response,
  onEvent: (event: RunEvent) => void,
  onMalformed: (error: Error) => void = () => undefined,
): Promise<void> {
  if (!response.body) throw new Error('ストリーム応答を読み取れません');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const processEvent = (block: string) => {
    try {
      const event = parseSseBlock(block);
      if (event) onEvent(event);
    } catch (error) {
      onMalformed(error instanceof Error ? error : new Error('SSEイベントを解釈できません'));
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const blocks = buffer.match(/(?:\r?\n){2}/g);
      if (blocks) {
        let remaining = buffer;
        for (const delimiter of blocks) {
          const index = remaining.indexOf(delimiter);
          const block = remaining.slice(0, index);
          remaining = remaining.slice(index + delimiter.length);
          processEvent(block);
        }
        buffer = remaining;
      }
      if (done) break;
    }
    buffer += decoder.decode();
    if (buffer.trim()) processEvent(buffer);
  } finally {
    reader.releaseLock();
  }
}
