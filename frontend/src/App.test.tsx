import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { downloadExport } from './export';
import type { ColumnId, ColumnResult, RunEvent } from './types';

vi.mock('./export', () => ({ downloadExport: vi.fn().mockResolvedValue(undefined) }));

describe('comparison form', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('starts with free entry and offers five optional sample questions', async () => {
    const config = {
      pricing: { version: '2026.1', currency: 'USD' },
      demoMode: true,
      limits: { columns: 3, allowedDomains: 100, questionMaxLength: 1000 },
      pack: {
        id: 'manufacturing',
        title: '製造業パック',
        description: '規制とサプライチェーン',
        scopeName: '製造業スコープ',
        allowedDomains: [],
        classifications: [],
        presets: Array.from({ length: 5 }, (_, index) => ({
          id: `p${index + 1}`,
          label: `質問 ${index + 1}`,
          question: `調査質問 ${index + 1}`,
          mode: 'lite',
          useScope: index === 0,
          responseFilter: index === 3 ? ['weather', 'news'] : ['web', 'news'],
        })),
      },
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify(config), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    ));

    render(<App />);

    await screen.findByText('サンプル質問を使う');
    expect(screen.getByLabelText('質問')).toHaveValue('');
    expect(screen.queryByText('ライブ比較')).not.toBeInTheDocument();
    expect(screen.queryByText('対象パック')).not.toBeInTheDocument();
    expect(screen.queryByText(/同じ問いを/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('サンプル質問を使う'));
    expect(screen.getByRole('button', { name: /質問 5/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /質問 4/ }));
    await waitFor(() => expect(screen.getByLabelText('質問')).toHaveValue('調査質問 4'));
    expect(screen.getByLabelText('Weather')).toBeChecked();
    expect(screen.getByRole('button', { name: /3列で比較を実行/ })).toBeEnabled();
  });

  describe('comparison results', () => {
    afterEach(() => {
      vi.unstubAllGlobals();
      vi.clearAllMocks();
    });

    it('renders Markdown safely, omits missing citation fields and displays available cost', async () => {
      const result = resultFor('A', {
        answer: '# 見出し\n\n- 項目\n\n| 列 | 値 |\n| --- | --- |\n| x | y |\n\n[安全](https://example.com) [危険](javascript:alert(1))\n\n<script>bad()</script>',
        citations: [{
          id: 'citation-1', title: '出典タイトル', url: 'https://example.com/source', source: '取得不可',
          excerpt: '取得不可', publishedAt: '', dateKind: '取得不可', evidenceIds: ['e1'], classification: '取得不可',
        }, {
          id: 'citation-2', title: '取得不可', url: 'https://example.com/other', source: '提供元',
          excerpt: '取得済みの抜粋', publishedAt: '2026-01-01', dateKind: '公開日', evidenceIds: ['e2'], classification: '公的機関',
        }],
        evidence: [{
          id: 'e1', title: '根拠', url: 'https://example.com/source', source: '取得不可',
          text: '取得不可', citationIds: ['citation-1'], kind: 'evidence', structured: {},
        }, {
          id: 'e2', title: '根拠', url: 'https://example.com/other', source: '提供元',
          text: '取得済みの根拠', citationIds: ['citation-2'], kind: 'evidence', structured: {},
        }],
        metrics: { ...resultFor('A').metrics, estimatedCost: 0 },
      });
      const stream = await startResults();
      await emit(stream, { event: 'result', columnId: 'A', elapsedMs: 1, sequence: 1, result });

      const card = screen.getByRole('article', { name: 'A列' });
      expect(within(card).getByRole('heading', { name: '見出し' })).toBeInTheDocument();
      expect(within(card).getByRole('listitem', { name: '' })).toHaveTextContent('項目');
      expect(within(card).getByRole('table')).toBeInTheDocument();
      expect(within(card).getByRole('link', { name: '安全' })).toHaveAttribute('href', 'https://example.com/');
      expect(within(card).getByText('危険').closest('a')).toBeNull();
      expect(card.querySelector('script')).toBeNull();
      const citation = card.querySelector('.citation-card') as HTMLElement;
      expect(within(citation).getByRole('link', { name: '出典タイトル' })).toBeInTheDocument();
      expect(within(citation).queryByText('取得不可')).not.toBeInTheDocument();
      const secondCitation = card.querySelectorAll('.citation-card')[1] as HTMLElement;
      expect(within(within(secondCitation).getByRole('heading')).getByRole('link', { name: 'https://example.com/other' })).toBeInTheDocument();
      expect(within(secondCitation).getByText('提供元 · 2026-01-01')).toBeInTheDocument();
      expect(within(secondCitation).getByText('取得済みの抜粋')).toBeInTheDocument();
      expect(within(secondCitation).getByText('取得済みの根拠')).toBeInTheDocument();
      expect(within(card).getByText('推定費用')).toBeInTheDocument();
      expect(card.textContent!.indexOf('進行タイムライン')).toBeLessThan(card.textContent!.indexOf('実行指標'));
      expect(card.textContent!.indexOf('実行指標')).toBeLessThan(card.textContent!.indexOf('回答'));
      await closeStream(stream);
    });

    it('toggles columns while running, retains results, hides unavailable cost and exports all columns', async () => {
      const stream = await startResults();
      for (const id of ['A', 'B', 'C']) {
        expect(screen.getByRole('button', { name: id })).toHaveAttribute('aria-pressed', 'true');
      }
      await emit(stream, { event: 'progress', columnId: 'B', elapsedMs: 1, sequence: 1, message: '検索中' });
      fireEvent.click(screen.getByRole('button', { name: 'A' }));
      expect(screen.queryByRole('article', { name: 'A列' })).not.toBeInTheDocument();
      expect(screen.getByRole('article', { name: 'B列' })).toBeInTheDocument();
      expect(screen.getByRole('article', { name: 'C列' })).toBeInTheDocument();
      expect(document.querySelector('#result-panel')).toHaveStyle('--visible-columns: 2');
      expect(screen.getByText('検索中')).toBeInTheDocument();
      await emit(stream, { event: 'result', columnId: 'A', elapsedMs: 2, sequence: 2, result: resultFor('A') });
      await emit(stream, { event: 'result', columnId: 'B', elapsedMs: 3, sequence: 2,
        result: resultFor('B', { metrics: { ...resultFor('B').metrics, estimatedCost: null } }) });
      expect(screen.queryByText('推定費用')).not.toBeInTheDocument();
      await emit(stream, { event: 'result', columnId: 'C', elapsedMs: 4, sequence: 1, result: resultFor('C') });
      await closeStream(stream);

      fireEvent.click(screen.getByRole('button', { name: 'C' }));
      expect(screen.queryByRole('article', { name: 'C列' })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'A' }));
      expect(document.querySelector('#result-panel')).toHaveStyle('--visible-columns: 2');
      expect(screen.getByRole('button', { name: 'A' })).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('button', { name: 'B' })).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('button', { name: 'C' })).toHaveAttribute('aria-pressed', 'false');
      expect(screen.getByRole('article', { name: 'A列' })).toHaveTextContent('回答 A');
      fireEvent.click(screen.getByRole('button', { name: /JSON/ }));
      await waitFor(() => expect(downloadExport).toHaveBeenCalled());
      const snapshot = vi.mocked(downloadExport).mock.calls[0][1];
      expect(snapshot.columns.map((column) => column.columnId)).toEqual(['A', 'B', 'C']);
    });
  });

  function resultFor(columnId: ColumnId, overrides: Partial<ColumnResult> = {}): ColumnResult {
    return {
      columnId, label: `${columnId}の結果`, status: 'success', answer: `回答 ${columnId}`, citations: [], evidence: [],
      settings: {}, metrics: {
        elapsedMs: 120, inputTokens: 10, outputTokens: 20, reasoningTokens: 0, searchRequests: 1,
        searchRequestUnit: 'request', estimatedCost: 0.25, costCurrency: 'USD', unavailableFields: [],
      },
      ...overrides,
    };
  }

  async function startResults(): Promise<ReadableStreamDefaultController<Uint8Array>> {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
    const config = {
      pricing: { version: 'v', currency: 'USD' }, demoMode: true,
      limits: { columns: 3, allowedDomains: 100, questionMaxLength: 1000 },
      pack: { id: 'p', title: 'テストパック', description: '', scopeName: null, allowedDomains: [], classifications: [],
        presets: [{ id: 'p1', label: '質問1', question: '質問', mode: 'lite', useScope: false, responseFilter: ['web'] }] },
    };
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(config), { headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })));
    render(<App />);
    await screen.findByText('サンプル質問を使う');
    fireEvent.change(screen.getByLabelText('質問'), { target: { value: '質問' } });
    fireEvent.click(screen.getByRole('button', { name: /3列で比較を実行/ }));
    return controller;
  }

  async function emit(controller: ReadableStreamDefaultController<Uint8Array>, event: RunEvent) {
    await act(async () => { controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`)); });
  }

  async function closeStream(controller: ReadableStreamDefaultController<Uint8Array>) {
    await act(async () => { controller.close(); });
  }
});
