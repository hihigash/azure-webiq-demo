import { useEffect, useLayoutEffect, useReducer, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { downloadExport } from './export';
import { formatCost, formatDuration, formatNumber, safeHttpUrl, unavailable } from './format';
import { initialRunState, runReducer } from './state';
import { consumeSse } from './stream';
import type { ColumnId, ColumnState, Config, Preset, RunMode, RunRequest, RunSnapshot } from './types';

const columnDescriptions: Record<ColumnId, string> = {
  A: '検索制限なし',
  B: '許可ドメインのみ',
  C: 'Microsoft Web IQ',
};

const filters = [
  { id: 'web', label: 'Web' },
  { id: 'news', label: 'News' },
  { id: 'weather', label: 'Weather' },
];

const resultColumns = ['A', 'B', 'C'] as const;

function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState('');
  const [presetId, setPresetId] = useState<string>();
  const [scopeEnabled, setScopeEnabled] = useState(false);
  const [mode, setMode] = useState<RunMode>('lite');
  const [responseFilter, setResponseFilter] = useState<string[]>(['web', 'news']);
  const [notice, setNotice] = useState<string | null>(null);
  const [exporting, setExporting] = useState<'json' | 'csv' | null>(null);
  const [visibleColumns, setVisibleColumns] = useState<Record<ColumnId, boolean>>({ A: true, B: true, C: true });
  const [run, dispatch] = useReducer(runReducer, undefined, initialRunState);
  const abortRef = useRef<AbortController | null>(null);
  const resultPanelRef = useRef<HTMLDivElement | null>(null);
  const [alignedHeights, setAlignedHeights] = useState({ header: 0, timeline: 0 });

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/config', { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('設定を読み込めませんでした');
        const data = await response.json() as Config;
        setConfig(data);
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          setConfigError(error instanceof Error ? error.message : '設定を読み込めませんでした');
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);

  useLayoutEffect(() => {
    const panel = resultPanelRef.current;
    if (!panel) return;
    if (resultColumns.filter((id) => visibleColumns[id]).length < 2) {
      setAlignedHeights((old) => old.header === 0 && old.timeline === 0 ? old : { header: 0, timeline: 0 });
      return;
    }
    const headers = Array.from(panel.querySelectorAll<HTMLElement>('.column-header-inner'));
    const timelines = Array.from(panel.querySelectorAll<HTMLElement>('.timeline-inner'));
    const measure = () => {
      const header = Math.max(0, ...headers.map((item) => item.getBoundingClientRect().height)) + 41;
      const timeline = Math.max(0, ...timelines.map((item) => item.getBoundingClientRect().height)) + 41;
      setAlignedHeights((old) => old.header === header && old.timeline === timeline ? old : { header, timeline });
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    [...headers, ...timelines].forEach((item) => observer?.observe(item));
    window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [visibleColumns, run.columns]);

  function selectPreset(preset: Preset) {
    setPresetId(preset.id);
    setPrompt(preset.question);
    setScopeEnabled(preset.useScope);
    setMode(preset.mode);
    setResponseFilter(preset.responseFilter.length ? [...preset.responseFilter] : ['web', 'news']);
    setNotice(null);
  }

  function changePrompt(value: string) {
    setPrompt(value);
    setPresetId(undefined);
  }

  async function startRun() {
    if (!prompt.trim() || run.running || !config) return;
    setNotice(null);
    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: 'start', timestamp: new Date().toISOString() });
    const request: RunRequest = {
      question: prompt.trim(),
      ...(presetId ? { presetId } : {}),
      ...(scopeEnabled && config.pack.scopeName ? { scopeName: config.pack.scopeName } : {}),
      mode,
      responseFilter,
    };

    try {
      const response = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(request),
        signal: controller.signal,
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `実行要求に失敗しました（HTTP ${response.status}）`);
      }
      if (!response.headers.get('Content-Type')?.includes('text/event-stream')) {
        throw new Error('SSE形式の応答ではありません');
      }
      await consumeSse(
        response,
        (event) => dispatch({ type: 'event', event }),
        (error) => setNotice(`イベントを処理できませんでした: ${error.message}`),
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) {
        dispatch({
          type: 'fatal',
          message: error instanceof Error ? error.message : '比較処理に失敗しました',
          timestamp: new Date().toISOString(),
        });
      } else {
        dispatch({
          type: 'fatal',
          message: '処理を中止しました',
          timestamp: new Date().toISOString(),
        });
      }
    } finally {
      abortRef.current = null;
    }
  }

  async function exportRun(format: 'json' | 'csv') {
    if (!config || run.running || !run.completedAt) return;
    setExporting(format);
    setNotice(null);
    try {
      const columns = (Object.values(run.columns)
        .map((column) => column.result)
        .filter((column) => column !== null));
      if (!columns.length) throw new Error('書き出せる実行結果がありません');
      const snapshot: RunSnapshot = {
        runId: crypto.randomUUID(),
        question: prompt,
        columns,
        settings: {
          ...(presetId ? { presetId } : {}),
          ...(scopeEnabled && config.pack.scopeName ? { scopeName: config.pack.scopeName } : {}),
          mode,
          responseFilter,
          startedAt: run.startedAt,
          completedAt: run.completedAt,
        },
        pricingVersion: config.pricing.version,
        createdAt: run.completedAt ?? new Date().toISOString(),
      };
      await downloadExport(format, snapshot);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '書き出しに失敗しました');
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Web IQ 比較デモ ホーム">
          <span className="brand-mark" aria-hidden="true">IQ</span>
          <span>
            <strong>Web IQ 比較デモ</strong>
            <small>Manufacturing intelligence</small>
          </span>
        </a>
      </header>

      <main>
        <section className="control-panel" aria-labelledby="question-heading">
          <div className="section-heading">
            <div className="step-number">01</div>
            <div>
              <h2 id="question-heading">比較する質問を入力</h2>
              <p>調査したい内容を自由に入力してください。必要な場合だけサンプル質問を使えます。</p>
            </div>
          </div>

          {configError ? (
            <div className="alert" role="alert">{configError}。サーバーの状態を確認して再読み込みしてください。</div>
          ) : !config ? (
            <div className="loading-state" role="status"><span className="spinner" />設定を読み込み中…</div>
          ) : (
            <>
              <div className="question-layout">
                <div className="question-input">
                  <div className="textarea-wrap">
                    <label htmlFor="prompt">質問</label>
                    <textarea
                      id="prompt"
                      value={prompt}
                      onChange={(event) => changePrompt(event.target.value)}
                      maxLength={1000}
                      placeholder="調査したい質問を入力してください"
                      disabled={run.running}
                      aria-describedby="prompt-count"
                    />
                    <span id="prompt-count" className="character-count">{prompt.length} / 1000</span>
                  </div>
                  <details className="sample-questions">
                    <summary>サンプル質問を使う</summary>
                    <div className="preset-grid" aria-label="サンプル質問">
                      {config.pack.presets.map((preset, index) => (
                        <button
                          className={`preset-button ${preset.id === presetId ? 'selected' : ''}`}
                          type="button"
                          key={preset.id}
                          onClick={() => selectPreset(preset)}
                          disabled={run.running}
                        >
                          <span className="preset-index">{String(index + 1).padStart(2, '0')}</span>
                          <span>{preset.label}</span>
                          <span className="preset-arrow" aria-hidden="true">↗</span>
                        </button>
                      ))}
                    </div>
                  </details>
                </div>

                <fieldset className="options-card">
                  <legend>列 C の実行設定</legend>
                  <label htmlFor="scope">
                    スコープ
                    <select
                      id="scope"
                      value={scopeEnabled ? (config.pack.scopeName ?? '') : ''}
                      onChange={(event) => setScopeEnabled(Boolean(event.target.value))}
                      disabled={run.running}
                    >
                      <option value="">スコープなし</option>
                      <option value={config.pack.scopeName ?? ''}>{config.pack.scopeName || 'スコープ未設定'}</option>
                    </select>
                  </label>
                  <label htmlFor="mode">
                    モード
                    <select
                      id="mode"
                      value={mode}
                      onChange={(event) => setMode(event.target.value as RunMode)}
                      disabled={run.running}
                    >
                      <option value="lite">Auto（lite）</option>
                      <option value="advanced">Auto Advanced</option>
                    </select>
                  </label>
                  <div>
                    <span className="field-label">レスポンスフィルター</span>
                    <div className="filter-options">
                      {filters.map((filter) => (
                        <label className="check-label" key={filter.id}>
                          <input
                            type="checkbox"
                            checked={responseFilter.includes(filter.id)}
                            disabled={run.running}
                            onChange={(event) => setResponseFilter((items) =>
                              event.target.checked
                                ? [...items, filter.id]
                                : items.filter((item) => item !== filter.id))}
                          />
                          {filter.label}
                        </label>
                      ))}
                    </div>
                  </div>
                </fieldset>
              </div>

              <div className="run-bar">
                <div className="run-actions">
                  {run.running ? (
                    <button className="secondary-button" type="button" onClick={() => abortRef.current?.abort()}>
                      中止する
                    </button>
                  ) : (
                    <button
                      className="primary-button"
                      type="button"
                      onClick={startRun}
                      disabled={!prompt.trim() || responseFilter.length === 0}
                    >
                      <span aria-hidden="true">▶</span> 3列で比較を実行
                    </button>
                  )}
                </div>
              </div>
            </>
          )}
          {notice && <div className="alert" role="alert">{notice}</div>}
        </section>

        <section className="results-section" aria-labelledby="results-heading" aria-live="polite">
          <div className="results-title">
            <div className="section-heading">
              <div className="step-number">02</div>
              <div>
                <h2 id="results-heading">回答と根拠を比較</h2>
                <p>各列は独立して進行します。一部が失敗しても、他の結果は保持されます。</p>
              </div>
            </div>
            <div className="export-actions">
              <button type="button" className="text-button" disabled={run.running || !run.completedAt || exporting !== null} onClick={() => exportRun('json')}>
                ↓ JSON
              </button>
              <button type="button" className="text-button" disabled={run.running || !run.completedAt || exporting !== null} onClick={() => exportRun('csv')}>
                ↓ CSV
              </button>
              {exporting && <span>書き出し中…</span>}
            </div>
          </div>

          <div className="result-toggles" role="group" aria-label="表示する列">
            <span>表示列</span>
            {resultColumns.map((id) => (
              <button
                key={id}
                type="button"
                aria-pressed={visibleColumns[id]}
                aria-controls={`result-column-${id}`}
                onClick={() => setVisibleColumns((current) => ({ ...current, [id]: !current[id] }))}
              >
                {id}
              </button>
            ))}
          </div>
          <div id="result-panel" ref={resultPanelRef}
            style={{
              '--comparison-header-height': `${alignedHeights.header}px`,
              '--comparison-timeline-height': `${alignedHeights.timeline}px`,
              '--visible-columns': Math.max(1, resultColumns.filter((id) => visibleColumns[id]).length),
            } as CSSProperties}
            className="comparison-grid">
            {resultColumns.filter((id) => visibleColumns[id]).map((id) => (
              <div id={`result-column-${id}`} key={id}>
                <ColumnCard column={run.columns[id]} scopeName={config?.pack.scopeName ?? undefined} />
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer>
        <span>Web IQ Comparison Lab</span>
        <span>根拠は提供元の規約に従って確認してください</span>
      </footer>
    </div>
  );
}

function ColumnCard({ column, scopeName }: { column: ColumnState; scopeName?: string }) {
  const result = column.result;
  const metrics = result?.metrics;
  return (
    <article className={`column-card column-${column.id.toLowerCase()}`} aria-label={`${column.id}列`}>
      <header className="column-header">
        <div className="column-header-inner">
        <div className="column-key">{column.id}</div>
        <div>
          <h3>{column.name}</h3>
          <p>{columnDescriptions[column.id]}</p>
        </div>
        <StatusBadge status={column.status} />
        </div>
      </header>

      <div className="column-body">
        <section className="timeline-section">
          <div className="timeline-inner">
          <div className="subhead"><h4>進行タイムライン</h4><span>{column.progress.length} 件</span></div>
          {column.status === 'idle' && <p className="empty-copy">比較を実行すると、取得した順に進行状況を表示します。</p>}
          {column.progress.length > 0 && (
            <ol className="timeline">
              {column.progress.map((item) => (
                <li key={`${item.sequence}-${item.elapsedMs}`}>
                  <span className="timeline-dot" aria-hidden="true" />
                  <p>{item.message}</p>
                  <time>#{item.sequence} · +{formatDuration(item.elapsedMs)}</time>
                </li>
              ))}
            </ol>
          )}
          {column.status === 'running' && <div className="streaming"><span className="spinner small" />イベント受信中</div>}
          </div>
        </section>

        <section className="metrics-section">
          <div className="subhead"><h4>実行指標</h4><span>観測値</span></div>
          {metrics ? (
            <>
              <div className="metrics-grid">
                <Metric label="処理時間" value={formatDuration(metrics.elapsedMs)} />
                <Metric label="入力トークン" value={formatNumber(metrics.inputTokens)} />
                <Metric label="推論トークン" value={formatNumber(metrics.reasoningTokens)} />
                <Metric label="出力トークン" value={formatNumber(metrics.outputTokens)} />
                <Metric label="検索リクエスト" value={formatNumber(metrics.searchRequests)} />
                {metrics.estimatedCost != null && (
                  <Metric label="推定費用" value={formatCost(metrics.estimatedCost, metrics.costCurrency ?? '', !metrics.unavailableFields.includes('estimatedCost'))} />
                )}
              </div>
              <p className="metric-note">
                {column.id === 'C' ? '検索リクエストは Web IQ API リクエスト数です。内部検索回数を表しません。' : 'A/B の検索回数は Bing 検索リクエスト数です。欠損値は 0 ではなく取得不可として表示します。'}
              </p>
            </>
          ) : <p className="empty-copy">結果を待機中</p>}
        </section>

        {column.error && <div className="error-box" role="alert"><strong>処理エラー</strong><p>{column.error}</p></div>}

        {result && (
          <>
            <section className="answer-section">
              <div className="subhead"><h4>回答</h4><span>{result.status === 'success' ? '完了' : 'エラー'}</span></div>
              <div className="answer-text">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  skipHtml
                  components={{
                    a: ({ href, children }) => {
                      const safeUrl = safeHttpUrl(href);
                      return safeUrl ? <a href={safeUrl} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
                    },
                    img: ({ alt }) => <span>{alt}</span>,
                  }}
                >
                  {result.answer || unavailable}
                </ReactMarkdown>
              </div>
            </section>

            {column.id === 'C' && (
              <div className={`scope-status ${result.scopeApplied === true ? 'applied' : result.scopeApplied === false ? 'not-applied' : ''}`}>
                <span>スコープ</span>
                <strong>{result.scopeApplied === true ? '適用済み' : result.scopeApplied === false ? '未適用' : 'スコープなし'}</strong>
                {result.scopeApplied === true && <small>{scopeName || unavailable}</small>}
              </div>
            )}

            <section className="citation-section">
              <div className="subhead"><h4>引用・根拠</h4><span>{result.citations.length} 件</span></div>
              {result.citations.length === 0
                ? <p className="empty-copy">根拠なし</p>
                : <div className="citation-list">{result.citations.map((citation, index) => {
                  const href = safeHttpUrl(citation.url);
                  const title = availableText(citation.title) || href || '引用';
                  const sourceLine = [availableText(citation.source), availableText(citation.publishedAt)].filter(Boolean).join(' · ');
                  const excerpt = availableText(citation.excerpt);
                  const classification = availableText(citation.classification);
                  const id = availableText(citation.id);
                  const dateKind = availableText(citation.dateKind);
                  const evidenceTexts = citation.evidenceIds
                    .map((evidenceId) => ({ id: evidenceId, text: availableText(result.evidence.find((item) => item.id === evidenceId)?.text) }))
                    .filter((item) => item.text);
                  return (
                    <article className="citation-card" key={`${citation.id}-${index}`}>
                      <div className="citation-heading">
                        <span className="citation-number">{index + 1}</span>
                        {classification && <span className="category-badge">{classification}</span>}
                      </div>
                      <h5>{href
                        ? <a href={href} target="_blank" rel="noopener noreferrer">{title}</a>
                        : <span>{title}</span>}
                      </h5>
                      {sourceLine && <p className="source-line">{sourceLine}</p>}
                      {excerpt && <p className="excerpt">{excerpt}</p>}
                      {(id || href || dateKind || evidenceTexts.length > 0) && <details>
                        <summary>根拠の詳細</summary>
                        <dl>
                          {id && <div><dt>根拠 ID</dt><dd>{id}</dd></div>}
                          {href && <div><dt>URL</dt><dd><a href={href} target="_blank" rel="noopener noreferrer">{href}</a></dd></div>}
                          {dateKind && <div><dt>日付種別</dt><dd>{dateKind}</dd></div>}
                          {evidenceTexts.map((item) => <div key={item.id}><dt>根拠本文</dt><dd>{item.text}</dd></div>)}
                        </dl>
                      </details>}
                    </article>
                  );
                })}</div>}
            </section>

          </>
        )}
      </div>
    </article>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function StatusBadge({ status }: { status: ColumnState['status'] }) {
  const labels = { idle: '待機中', running: '実行中', completed: '完了', error: 'エラー' };
  return <span className={`status-badge ${status}`}><span aria-hidden="true" />{labels[status]}</span>;
}

function availableText(value: string | null | undefined): string | null {
  const text = value?.trim();
  return text && text !== unavailable ? text : null;
}

export default App;
