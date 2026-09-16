import { describe, expect, it } from 'vitest';
import { TUTORIAL_STEP_DEFS, buildTutorialSteps } from '@/lib/tutorialSteps';

const allPresent = () => true;
const nonePresent = (sel: string) => sel === '#terminal-command-input';

describe('buildTutorialSteps', () => {
  it('emits one step per def plus a closing summary when everything is on screen', () => {
    const { steps, skipped } = buildTutorialSteps(allPresent);
    expect(skipped).toEqual([]);
    expect(steps).toHaveLength(TUTORIAL_STEP_DEFS.length + 1);
    expect(steps[0].popover?.title).toBe('Command bar');
    const last = steps[steps.length - 1];
    expect(last.popover?.title).toBe('You are set up');
    expect(last.popover?.description).toContain('TOUR');
  });

  it('skips widgets that are not on screen and folds them into the summary', () => {
    // Only the command bar and CHART panel are visible
    const exists = (sel: string) =>
      sel === '#terminal-command-input' || sel === '[data-tour-panel="CHART"]';
    const { steps, skipped } = buildTutorialSteps(exists);

    expect(skipped.map((s) => s.command)).toContain('NEWS');
    expect(skipped.map((s) => s.command)).toContain('AI');
    // Present steps + summary
    expect(steps).toHaveLength(TUTORIAL_STEP_DEFS.length - skipped.length + 1);
    const summary = steps[steps.length - 1].popover?.description ?? '';
    expect(summary).toContain('type NEWS');
    expect(summary).toContain('type AI');
  });

  it('never errors when nothing matches and always ends with a summary', () => {
    const { steps, skipped } = buildTutorialSteps(() => false);
    expect(skipped).toHaveLength(TUTORIAL_STEP_DEFS.length);
    expect(steps).toHaveLength(1);
    expect(steps[0].element).toBe('#terminal-command-input');
    expect(steps[0].popover?.title).toBe('You are set up');
  });

  it('every skippable def carries a command so users can open it manually', () => {
    for (const def of TUTORIAL_STEP_DEFS) {
      if (def.id === 'command-bar' || def.id === 'panels') continue;
      expect(def.command.length).toBeGreaterThan(0);
    }
  });

  it('nonePresent helper sanity: command bar is always the summary anchor', () => {
    const { steps } = buildTutorialSteps(nonePresent);
    expect(steps[0].element).toBe('#terminal-command-input');
  });
});
