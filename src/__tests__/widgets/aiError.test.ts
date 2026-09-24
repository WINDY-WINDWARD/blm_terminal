import { describe, expect, it } from 'vitest';
import { modeKnobClass, modeTrackClass, sanitizeAiErrorMessage, shortModelLabel } from '@/components/widgets/AiWidget';

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

describe('AI sliding mode-switch hues', () => {
  it('track is tinted with the active hue', () => {
    expect(modeTrackClass('research')).toContain('bg-terminal-amber');
    expect(modeTrackClass('script')).toContain('bg-emerald-400');
    expect(modeTrackClass('research')).not.toContain('emerald');
    expect(modeTrackClass('script')).not.toContain('terminal-amber');
  });

  it('knob is a solid pill parked on the active side', () => {
    const r = modeKnobClass('research');
    const s = modeKnobClass('script');
    for (const cls of [r, s]) {
      expect(cls).toContain('text-black');
      expect(cls).toContain('font-bold');
    }
    expect(r).toContain('bg-terminal-amber');
    expect(r).toContain('left-[2px]');
    expect(s).toContain('bg-emerald-400');
    expect(s).toContain('left-[calc(50%+1px)]');
  });
});

describe('shortModelLabel', () => {
  it('strips [Provider] prefixes, leaves plain labels', () => {
    expect(shortModelLabel('[Zen] kimi-k2.5')).toBe('kimi-k2.5');
    expect(shortModelLabel('gpt-4o')).toBe('gpt-4o');
  });
});
