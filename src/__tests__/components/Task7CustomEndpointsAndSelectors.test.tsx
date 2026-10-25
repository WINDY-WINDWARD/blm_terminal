import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RouteModelSelect } from '@/components/ai/RouteModelSelect';
import { AiModelDropdown } from '@/components/widgets/AiWidget';
import type { RouteModelCatalogEntry } from '@/types/aiRoutes';

const antigravityRoute: RouteModelCatalogEntry = {
  route_id: 'oauth:antigravity',
  label: 'Antigravity',
  kind: 'oauth',
  provider: 'antigravity',
  models: [
    { id: 'blm:oauth:antigravity/gemini-3.8-flash-high', label: 'gemini-3.8-flash-high' },
  ],
};

const codexRoute: RouteModelCatalogEntry = {
  route_id: 'oauth:codex',
  label: 'Codex',
  kind: 'oauth',
  provider: 'codex',
  models: [
    { id: 'blm:oauth:codex/gpt-5-codex', label: 'gpt-5-codex' },
  ],
};

describe('RouteModelSelect', () => {
  it('groups model options by configured route', () => {
    render(
      <RouteModelSelect
        label="Hunter model"
        value=""
        routes={[antigravityRoute, codexRoute]}
        helperText="Choose a model for market scans."
        onChange={vi.fn()}
      />,
    );

    const select = screen.getByRole('combobox', { name: 'Hunter model' });
    expect(select).toHaveAttribute('aria-describedby');
    expect(document.getElementById(select.getAttribute('aria-describedby')!)).toHaveTextContent(
      'Choose a model for market scans.',
    );
    expect(within(select).getByRole('group', { name: 'Antigravity' })).toBeInTheDocument();
    expect(within(select).getByRole('group', { name: 'Codex' })).toBeInTheDocument();
    expect(within(select).getByRole('option', { name: 'gpt-5-codex' })).toHaveValue(
      'blm:oauth:codex/gpt-5-codex',
    );
  });

  it('preserves a saved cross-route model after the catalog rerenders', () => {
    const props = {
      label: 'Verifier model',
      value: 'blm:oauth:codex/gpt-5-codex',
      helperText: 'Choose a model for verification.',
      onChange: vi.fn(),
    };
    const { rerender } = render(<RouteModelSelect {...props} routes={[codexRoute, antigravityRoute]} />);

    rerender(<RouteModelSelect {...props} routes={[antigravityRoute, codexRoute]} />);

    expect(screen.getByRole('combobox', { name: 'Verifier model' })).toHaveValue(
      'blm:oauth:codex/gpt-5-codex',
    );
  });

  it('keeps a missing saved model as a disabled warning option', () => {
    const savedModel = 'blm:oauth:codex/removed-model';
    render(
      <RouteModelSelect
        label="Hunter model"
        value={savedModel}
        routes={[antigravityRoute]}
        helperText="Choose a model for market scans."
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole('combobox', { name: 'Hunter model' })).toHaveValue(savedModel);
    expect(screen.getByRole('option', { name: /removed-model.*unavailable/i })).toBeDisabled();
  });

  it('explains how to add models when no route has any', () => {
    const onChange = vi.fn();
    render(
      <RouteModelSelect
        label="Hunter model"
        value=""
        routes={[]}
        helperText="Choose a model for market scans."
        onChange={onChange}
      />,
    );

    expect(screen.getByRole('option', { name: 'No models available - open provider manager' })).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Hunter model' }), { target: { value: '' } });
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('offers an inline retry when chat model discovery fails', () => {
    const onRetry = vi.fn();
    render(
      <AiModelDropdown
        value=""
        availableModels={[]}
        loadError
        onRetry={onRetry}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Model list unavailable - retry/ }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('groups chat models under each configured route header', () => {
    render(
      <AiModelDropdown
        value="blm:oauth:codex/gpt-5-codex"
        onChange={vi.fn()}
        availableModels={[
          { id: 'blm:oauth:antigravity/gemini-3.8-flash-high', label: '[Antigravity] gemini-3.8-flash-high' },
          { id: 'blm:oauth:codex/gpt-5-codex', label: '[Codex] gpt-5-codex' },
        ]}
        routeGroups={[
          {
            route_id: 'oauth:antigravity',
            label: 'Antigravity',
            models: [{ id: 'blm:oauth:antigravity/gemini-3.8-flash-high', label: 'gemini-3.8-flash-high' }],
          },
          {
            route_id: 'oauth:codex',
            label: 'Codex',
            models: [{ id: 'blm:oauth:codex/gpt-5-codex', label: 'gpt-5-codex' }],
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByTestId('ai-model-select'));
    expect(screen.getByText('Antigravity')).toBeInTheDocument();
    expect(screen.getByText('Codex')).toBeInTheDocument();
    expect(screen.getByText('gpt-5-codex')).toBeInTheDocument();
  });
});
