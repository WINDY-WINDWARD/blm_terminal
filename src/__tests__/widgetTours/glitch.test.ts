import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

describe('WidgetTourOverlay oscillation fix', () => {
  const filePath = path.resolve(__dirname, '../../components/widgetTour/WidgetTourOverlay.tsx');
  const source = readFileSync(filePath, 'utf-8');

  it('popover measuring reads scrollHeight instead of offsetHeight', () => {
    expect(source).not.toMatch(/el\.offsetHeight/);
    expect(source).toMatch(/const\s+measured\s*=\s*el\.scrollHeight/);
  });

  it('popover measuring effect has explicit deps and does not re-trigger positionStep', () => {
    // Check measure effect pattern
    const measureEffectMatch = source.match(
      /\/\/\s*Measure the real popover height[\s\S]*?useEffect\(\(\)\s*=>\s*\{([\s\S]*?)\},\s*\[(.*?)\]\);/,
    );
    expect(measureEffectMatch).not.toBeNull();
    const [, effectBody, deps] = measureEffectMatch!;
    expect(deps).toContain('isActive');
    expect(deps).toContain('isAnchorFound');
    expect(deps).toContain('currentStep');
    expect(effectBody).not.toMatch(/positionStep/);
    expect(effectBody).toMatch(/setPopoverHeight\(measured\)/);
  });

  it('positionStep uses scrollHeight and clamps to panel height', () => {
    expect(source).toContain('Math.min(');
    expect(source).toContain('popoverRef.current?.scrollHeight ?? popoverHeightRef.current');
    expect(source).toContain('panelRect.height - 32');
  });

  it('positioningRef exists as a guard to drop concurrent positionStep calls', () => {
    expect(source).toMatch(/const\s+positioningRef\s*=\s*useRef\(false\)/);
    expect(source).toMatch(/if\s*\(positioningRef\.current\)\s*return;/);
  });

  it('ResizeObserver uses requestAnimationFrame and checks 2px delta', () => {
    expect(source).toMatch(/new\s+ResizeObserver/);
    expect(source).toMatch(/requestAnimationFrame/);
    expect(source).toMatch(/Math\.abs\(rect\.width\s*-\s*prevWidth\)\s*<\s*2/);
    expect(source).toMatch(/Math\.abs\(rect\.height\s*-\s*prevHeight\)\s*<\s*2/);
  });
});
