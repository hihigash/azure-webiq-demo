import { describe, expect, it } from 'vitest';
import { initialRunState, runReducer } from './state';
import type { ColumnResult, RunEvent } from './types';

const result: ColumnResult = {
  columnId: 'A',
  label: '標準検索',
  status: 'success',
  answer: '回答',
  citations: [],
  evidence: [],
  settings: {},
  metrics: {
    elapsedMs: 120,
    inputTokens: null,
    reasoningTokens: 0,
    outputTokens: 10,
    searchRequests: null,
    searchRequestUnit: 'test',
    estimatedCost: null,
    costCurrency: 'USD',
    unavailableFields: ['estimatedCost'],
  },
};

describe('run reducer', () => {
  it('keeps one column error independent from completed peers', () => {
    let state = runReducer(initialRunState(), { type: 'start', timestamp: 'start' });
    state = runReducer(state, { type: 'event', event: errorEvent('B') });
    state = runReducer(state, { type: 'event', event: resultEvent('A') });

    expect(state.columns.B.status).toBe('error');
    expect(state.columns.B.error).toBe('失敗');
    expect(state.columns.A.result?.answer).toBe('回答');
    expect(state.running).toBe(true);
  });

  it('replaces a prior run on start and clears progress', () => {
    const old = runReducer(initialRunState(), { type: 'start', timestamp: 'first' });
    const next = runReducer(old, { type: 'start', timestamp: 'second' });
    expect(next.startedAt).toBe('second');
    expect(next.columns.A.progress).toEqual([]);
    expect(next.columns.A.status).toBe('running');
  });
});

function errorEvent(column: 'A' | 'B' | 'C'): RunEvent {
  return { event: 'error', columnId: column, elapsedMs: 1, sequence: 1, message: '失敗' };
}

function resultEvent(column: 'A' | 'B' | 'C'): RunEvent {
  return { event: 'result', columnId: column, elapsedMs: 2, sequence: 2, result: { ...result, columnId: column } };
}
