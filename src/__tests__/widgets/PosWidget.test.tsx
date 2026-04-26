import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { render } from '../utils/renderWithProviders';
import { PosWidget } from '@/components/widgets/PosWidget';

describe('PosWidget', () => {
  it('renders without crashing', async () => {
    render(<PosWidget panelId="panel-1" />);
    // Widget should render without throwing
    await waitFor(() => {
      expect(screen.queryByText(/positions/i) || screen.queryByText(/loading/i)).toBeTruthy();
    }, { timeout: 5000 });
  });
});