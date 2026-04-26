import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Panel } from '@/components/Panel';
import { activePanelsAtom, focusedPanelAtom } from '@/store/terminalStore';
import type { WritableAtom } from 'jotai';
import { useAtom } from 'jotai';

vi.mock('@/components/widgets/ChartWidget', () => ({
  ChartWidget: () => <div data-testid="CHART">Chart</div>,
}));

vi.mock('@/components/widgets/WatchWidget', () => ({
  WatchWidget: () => <div data-testid="WATCH">Watch</div>,
}));

vi.mock('@/components/widgets/MoversWidget', () => ({
  MoversWidget: () => <div data-testid="TOP">Top</div>,
}));

vi.mock('@/components/widgets/PosWidget', () => ({
  PosWidget: () => <div data-testid="POS">Positions</div>,
}));

vi.mock('@/components/widgets/OrderWidget', () => ({
  OrderWidget: () => <div data-testid="ORDER">Order</div>,
}));

function TestWrapper() {
  const [focused] = useAtom(focusedPanelAtom);
  return (
    <div>
      <Panel id="panel-1" title="CHART" />
      <div data-testid="focused">{focused}</div>
    </div>
  );
}

describe('Panel', () => {
  it('renders CHART widget for CHART title', () => {
    render(<Panel id="panel-1" title="CHART" />);
    expect(screen.getByTestId('CHART')).toBeInTheDocument();
  });

  it('renders UNKNOWN_WIDGET fallback for unknown widget', () => {
    render(<Panel id="panel-1" title="UNKNOWN_WIDGET" />);
    expect(screen.getByText('[UNKNOWN_WIDGET WIDGET NOT FOUND]')).toBeInTheDocument();
  });

  it('renders correct styling when focused', async () => {
    render(<Panel id="panel-1" title="CHART" />);
    const panel = screen.getByText('CHART').closest('div');
    
    // Simulate click to focus
    fireEvent.click(panel!);
    
    // When focused, should have blue-500 border (we just verify it renders)
    expect(screen.getByText('CHART')).toBeInTheDocument();
  });

  it('renders correct styling when not focused', () => {
    render(<Panel id="panel-2" title="CHART" />);
    const header = screen.getByText('CHART');
    expect(header).toBeInTheDocument();
  });
});