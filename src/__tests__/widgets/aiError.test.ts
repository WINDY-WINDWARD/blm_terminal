import { describe, expect, it } from 'vitest';
import { modeChipClass, modeToggleClass, sanitizeAiErrorMessage } from '@/components/widgets/AiWidget';

describe('sanitizeAiErrorMessage', () => {
  it('replaces raw JSON error blobs with a generic line', () => {
    const blob =
      'Antigravity API 429: { "error": { "code": 429, "message": "quota reached';
    const out = sanitizeAiErrorMessage(blob);
    expect(out).not.toContain('{ "error"');
    expect(out).toContain('unreadable error');
  });

  it('passes friendly messages through untouched', () => {
    const msg = '⏳ Antigravity API daily quota reached — resets in ~19h56m.';
    expect(sanitizeAiErrorMessage(msg)).toBe(msg);
  });

  it('passes plain non-JSON errors through', () => {
    expect(sanitizeAiErrorMessage('Network error: boom')).toBe('Network error: boom');
  });
});

describe('AI mode hues (Issue 5)', () => {
  it('active mode is a solid pill with a per-mode hue', () => {
    expect(modeToggleClass('research', 'research')).toContain('bg-terminal-amber');
    expect(modeToggleClass('script', 'script')).toContain('bg-emerald-400');
    for (const cls of [modeToggleClass('research', 'research'), modeToggleClass('script', 'script')]) {
      expect(cls).toContain('text-black');
      expect(cls).toContain('font-bold');
    }
  });

  it('inactive mode is dim, never a solid pill', () => {
    expect(modeToggleClass('research', 'script')).not.toContain('bg-');
    expect(modeToggleClass('script', 'research')).not.toContain('bg-');
  });

  it('input chip mirrors the toggle hues', () => {
    expect(modeChipClass('research')).toContain('bg-terminal-amber');
    expect(modeChipClass('script')).toContain('bg-emerald-400');
  });
});
