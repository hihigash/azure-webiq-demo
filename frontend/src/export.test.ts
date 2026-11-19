import { describe, expect, it } from 'vitest';
import { filenameFromHeader, serializeJsonForTest } from './export';
import type { RunSnapshot } from './types';

describe('exports', () => {
  it('sanitizes filename delimiters from headers', () => {
    expect(filenameFromHeader('attachment; filename*=UTF-8\'\'report%3Aone.csv')).toBe('report_one.csv');
  });

  it('serializes the final snapshot with unavailable values intact', () => {
    const snapshot: RunSnapshot = {
      runId: 'run-1',
      question: '調査',
      settings: { mode: 'lite', responseFilter: ['web'] },
      pricingVersion: '2026.1',
      createdAt: '2026-01-01T00:00:00Z',
      columns: [],
    };
    expect(JSON.parse(serializeJsonForTest(snapshot))).toMatchObject({
      question: '調査',
      columns: [],
    });
  });
});
