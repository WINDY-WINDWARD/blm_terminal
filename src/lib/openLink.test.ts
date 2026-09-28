import { beforeEach, describe, expect, it, vi } from 'vitest';
import { isExternalClick, openLink } from './openLink';

describe('openLink', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    delete (window as unknown as { electronAPI?: unknown }).electronAPI;
  });

  it('routes app mode through electronAPI.openInApp', () => {
    const openInApp = vi.fn();
    (window as unknown as { electronAPI?: unknown }).electronAPI = { openInApp };
    openLink('https://example.com/a', 'app');
    expect(openInApp).toHaveBeenCalledWith('https://example.com/a');
  });

  it('routes external mode through electronAPI.openExternal', () => {
    const openExternal = vi.fn();
    (window as unknown as { electronAPI?: unknown }).electronAPI = { openExternal };
    openLink('https://youtu.be/x', 'external');
    expect(openExternal).toHaveBeenCalledWith('https://youtu.be/x');
  });

  it('falls back to window.open outside Electron', () => {
    const spy = vi.spyOn(window, 'open').mockReturnValue(null);
    openLink('https://example.com/b', 'app');
    expect(spy).toHaveBeenCalledWith('https://example.com/b', '_blank', 'noopener,noreferrer');
  });

  it('ignores empty urls', () => {
    const spy = vi.spyOn(window, 'open').mockReturnValue(null);
    openLink('', 'external');
    expect(spy).not.toHaveBeenCalled();
  });
});

describe('isExternalClick', () => {
  it('is true for Ctrl or Cmd clicks only', () => {
    expect(isExternalClick({ ctrlKey: true, metaKey: false })).toBe(true);
    expect(isExternalClick({ ctrlKey: false, metaKey: true })).toBe(true);
    expect(isExternalClick({ ctrlKey: false, metaKey: false })).toBe(false);
    expect(isExternalClick({ ctrlKey: true, metaKey: true })).toBe(true);
  });
});
