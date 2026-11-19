import { describe, expect, it } from 'vitest';
import { parseSseBlock } from './stream';

describe('parseSseBlock', () => {
  it('parses data split over multiple SSE data lines', () => {
    const event = parseSseBlock(
      'event: message\n' +
      'data: {"event":"progress","columnId":"A",\n' +
      'data: "elapsedMs":25,"sequence":1,"message":"検索中"}\n',
    );
    expect(event?.event).toBe('progress');
    expect(event?.message).toBe('検索中');
  });

  it('ignores comments and empty events', () => {
    expect(parseSseBlock(': heartbeat')).toBeNull();
  });

  it('rejects malformed JSON and invalid columns', () => {
    expect(() => parseSseBlock('data: not-json')).toThrow();
    expect(() => parseSseBlock(
      'data: {"event":"progress","columnId":"Z","elapsedMs":1,"sequence":1}',
    )).toThrow('SSEイベントの形式が不正です');
  });
});
