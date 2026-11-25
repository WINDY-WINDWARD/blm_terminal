import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '../utils/renderWithProviders';
import { ProviderRiskModal } from '@/components/modals/AiProvidersModal/ProviderRiskModal';
import type { ProviderRiskInfo } from '@/types/aiRoutes';

const risk: ProviderRiskInfo = {
  level: 'high',
  title: 'DO NOT USE - HIGH RISK OF ACCOUNT BAN',
  message: 'The provider can suspend or permanently ban the account.',
  acknowledged: false,
  gate_version: '2026.11.25',
  auto_disabled: true,
};

function renderModal(overrides: Partial<React.ComponentProps<typeof ProviderRiskModal>> = {}) {
  const props: React.ComponentProps<typeof ProviderRiskModal> = {
    isOpen: true,
    providerLabel: 'Claude',
    risk,
    isPending: false,
    error: null,
    onAccept: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<ProviderRiskModal {...props} />);
  return props;
}

describe('ProviderRiskModal', () => {
  it('renders the ban warning and provider label', () => {
    renderModal();

    expect(screen.getByTestId('provider-risk-modal')).toBeInTheDocument();
    expect(screen.getByText(/DO NOT USE - HIGH RISK OF ACCOUNT BAN/i)).toBeInTheDocument();
    expect(screen.getByText('Claude')).toBeInTheDocument();
    expect(screen.getByText(risk.message)).toBeInTheDocument();
    expect(screen.getByText(/cannot recover a banned account/i)).toBeInTheDocument();
  });

  it('keeps the accept action disabled until the checkbox is ticked', () => {
    const props = renderModal();

    const accept = screen.getByTestId('provider-risk-accept');
    expect(accept).toBeDisabled();
    expect(accept).toHaveTextContent(/I ACCEPT THE RISK/i);

    fireEvent.click(screen.getByRole('checkbox'));
    expect(accept).not.toBeDisabled();

    fireEvent.click(accept);
    expect(props.onAccept).toHaveBeenCalledTimes(1);
  });

  it('closes without accepting', () => {
    const props = renderModal();

    fireEvent.click(screen.getByTestId('provider-risk-cancel'));
    expect(props.onClose).toHaveBeenCalledTimes(1);
    expect(props.onAccept).not.toHaveBeenCalled();
  });

  it('shows a pending state and an error message', () => {
    renderModal({ isPending: true, error: 'Could not record risk acceptance' });

    expect(screen.getByText(/RECORDING\.\.\./i)).toBeInTheDocument();
    expect(screen.getByTestId('provider-risk-error')).toHaveTextContent(
      'Could not record risk acceptance',
    );
    expect(screen.getByTestId('provider-risk-accept')).toBeDisabled();
  });

  it('renders nothing when the risk payload is missing', () => {
    renderModal({ risk: null });

    expect(screen.queryByTestId('provider-risk-modal')).not.toBeInTheDocument();
  });
});