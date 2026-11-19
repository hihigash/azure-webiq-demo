export const unavailable = '取得不可';

export function formatNumber(value: number | null | undefined): string {
  return value == null ? unavailable : value.toLocaleString('ja-JP');
}

export function formatDuration(value: number | null | undefined): string {
  if (value == null) return unavailable;
  return value >= 1000 ? `${(value / 1000).toFixed(2)} 秒` : `${value.toLocaleString('ja-JP')} ms`;
}

export function formatCost(cost: number | null, currency: string, complete: boolean): string {
  if (cost == null) return unavailable;
  return `${new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 6 }).format(cost)} ${currency || unavailable}${complete ? '' : '（一部未算出）'}`;
}

export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

export function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? unavailable : date.toLocaleTimeString('ja-JP', { hour12: false });
}
