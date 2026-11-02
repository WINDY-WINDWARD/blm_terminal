export function resolveWidgetPanel(
  command: string,
  activePanels: Record<string, string>,
  panelCount: number,
  focusedPanel: string,
): string | null {
  const target = command.toUpperCase();
  if (focusedPanel && activePanels[focusedPanel]?.toUpperCase() === target) {
    return focusedPanel;
  }
  for (let i = 1; i <= panelCount; i++) {
    const key = `panel-${i}`;
    if (activePanels[key]?.toUpperCase() === target) {
      return key;
    }
  }
  return null;
}
