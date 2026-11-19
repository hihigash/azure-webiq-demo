import type { ColumnId, ColumnState, RunEvent, RunState } from './types';

const columns = ['A', 'B', 'C'] as const;

export const columnDefaults: Record<ColumnId, string> = {
  A: '標準検索',
  B: 'ドメイン制限検索',
  C: 'Web IQ',
};

export function initialRunState(): RunState {
  return {
    columns: {
      A: emptyColumn('A'),
      B: emptyColumn('B'),
      C: emptyColumn('C'),
    },
    running: false,
    startedAt: null,
    completedAt: null,
  };
}

function emptyColumn(id: ColumnId): ColumnState {
  return {
    id,
    name: columnDefaults[id],
    status: 'idle',
    progress: [],
    result: null,
    error: null,
  };
}

export type RunAction =
  | { type: 'start'; timestamp: string }
  | { type: 'event'; event: RunEvent }
  | { type: 'fatal'; message: string; timestamp: string };

export function runReducer(state: RunState, action: RunAction): RunState {
  if (action.type === 'start') {
    const base = initialRunState();
    return {
      ...base,
      running: true,
      startedAt: action.timestamp,
      columns: Object.fromEntries(columns.map((id) => [id, { ...base.columns[id], status: 'running' }])) as Record<ColumnId, ColumnState>,
    };
  }

  if (action.type === 'fatal') {
    return {
      ...state,
      running: false,
      completedAt: action.timestamp,
      columns: Object.fromEntries(columns.map((id) => {
        const column = state.columns[id];
        return [id, column.status === 'completed' || column.status === 'error'
          ? column
          : { ...column, status: 'error', error: action.message }];
      })) as Record<ColumnId, ColumnState>,
    };
  }

  const event = action.event;
  const current = state.columns[event.columnId];
  let column: ColumnState = { ...current };
  if (event.event === 'progress') {
    column = {
      ...column,
      status: 'running',
      progress: [...column.progress, {
        sequence: event.sequence,
        elapsedMs: event.elapsedMs,
        message: event.message ?? '処理中',
      }],
    };
  } else if (event.event === 'result' && event.result) {
    column = {
      ...column,
      name: event.result.label,
      status: event.result.status === 'success' ? 'completed' : 'error',
      result: event.result,
      error: event.result.error?.message ?? null,
    };
  } else if (event.event === 'error') {
    column = { ...column, status: 'error', error: event.message ?? '列の処理に失敗しました' };
  } else if (event.event === 'done' && current.status === 'running') {
    column = { ...column, status: 'error', error: '完了結果を受信せずに終了しました' };
  }

  const nextColumns = { ...state.columns, [event.columnId]: column };
  const running = columns.some((id) => nextColumns[id].status === 'running');
  return {
    ...state,
    columns: nextColumns,
    running,
    completedAt: running ? null : new Date().toISOString(),
  };
}
