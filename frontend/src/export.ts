import type { RunSnapshot } from './types';

export function makeSnapshotFilename(format: 'json' | 'csv', now = new Date()): string {
  const stamp = now.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  return `webiq-comparison-${stamp}.${format}`;
}

export async function downloadExport(format: 'json' | 'csv', snapshot: RunSnapshot): Promise<void> {
  const response = await fetch(`/api/export?format=${format}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: format === 'json' ? 'application/json' : 'text/csv' },
    body: JSON.stringify(snapshot),
  });
  if (!response.ok) throw new Error('書き出しに失敗しました');
  const blob = await response.blob();
  downloadBlob(blob, filenameFromHeader(response.headers.get('Content-Disposition')) ?? makeSnapshotFilename(format));
}

export function filenameFromHeader(value: string | null): string | null {
  if (!value) return null;
  const utf8 = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1]).replace(/[\\/:*?"<>|]/g, '_');
    } catch {
      return null;
    }
  }
  const plain = value.match(/filename="?([^";]+)"?/i);
  return plain ? plain[1].replace(/[\\/:*?"<>|]/g, '_') : null;
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function serializeJsonForTest(snapshot: RunSnapshot): string {
  return JSON.stringify(snapshot, null, 2);
}
