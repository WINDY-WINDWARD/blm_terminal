const istTimeFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Kolkata',
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

const istDateFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Kolkata',
  weekday: 'short',
  day: 'numeric',
  month: 'short',
});

/**
 * Parses a UTC ISO string, appending 'Z' when no timezone is present.
 * Backend timestamps are naive UTC ISO strings with no Z suffix.
 */
export function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso || typeof iso !== 'string') return null;
  const trimmed = iso.trim();
  if (!trimmed) return null;

  const normalized = trimmed.includes('T') ? trimmed : trimmed.replace(' ', 'T');
  const hasTimezone = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i.test(normalized);
  const withTz = hasTimezone ? normalized : `${normalized}Z`;

  const date = new Date(withTz);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Formats a timestamp into 'Mon 10:00' in Asia/Kolkata timezone.
 */
export function formatIst(iso: string | null | undefined): string {
  const date = parseUtc(iso);
  if (!date) return '';
  const parts = istTimeFormatter.formatToParts(date);
  const weekday = parts.find((p) => p.type === 'weekday')?.value ?? '';
  const hour = parts.find((p) => p.type === 'hour')?.value ?? '';
  const minute = parts.find((p) => p.type === 'minute')?.value ?? '';
  if (!weekday || !hour || !minute) return '';
  return `${weekday} ${hour}:${minute}`;
}

/**
 * Formats a timestamp into 'Mon, 3 Nov' in Asia/Kolkata timezone.
 */
export function formatIstDate(iso: string | null | undefined): string {
  const date = parseUtc(iso);
  if (!date) return '';
  const parts = istDateFormatter.formatToParts(date);
  const weekday = parts.find((p) => p.type === 'weekday')?.value ?? '';
  const day = parts.find((p) => p.type === 'day')?.value ?? '';
  const month = parts.find((p) => p.type === 'month')?.value ?? '';
  if (!weekday || !day || !month) return '';
  return `${weekday}, ${day} ${month}`;
}

/**
 * Formats relative time difference between target ISO and serverNowIso (or current time).
 * Produces strings like 'in 3h', '12m ago', or 'now'.
 */
export function formatRelative(
  iso: string | null | undefined,
  serverNowIso?: string | null | undefined,
): string {
  const targetDate = parseUtc(iso);
  if (!targetDate) return '';

  const nowDate = serverNowIso ? parseUtc(serverNowIso) ?? new Date() : new Date();
  const diffSeconds = Math.round((targetDate.getTime() - nowDate.getTime()) / 1000);

  if (Math.abs(diffSeconds) < 60) {
    return 'now';
  }

  if (diffSeconds > 0) {
    const mins = Math.floor(diffSeconds / 60);
    if (mins < 60) {
      return `in ${mins}m`;
    }
    const hours = Math.floor(mins / 60);
    if (hours < 24) {
      return `in ${hours}h`;
    }
    const days = Math.floor(hours / 24);
    return `in ${days}d`;
  }

  const absSec = Math.abs(diffSeconds);
  const mins = Math.floor(absSec / 60);
  if (mins < 60) {
    return `${mins}m ago`;
  }
  const hours = Math.floor(mins / 60);
  if (hours < 24) {
    return `${hours}h ago`;
  }
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
