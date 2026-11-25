import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '../utils/renderWithProviders';
import { EmptyChatState } from '@/components/widgets/AiChatStarterViews';
import { getResearchStarterPrompts } from '@/types/aiWidgetTypes';
import type { CustomPrompt } from '@/types/aiWorkflowTypes';

function makePrompt(id: number, title: string): CustomPrompt {
  return {
    id,
    title,
    tag: 'MACRO',
    description: `${title} description`,
    prompt: `Instruction for ${title}`,
    icon: '◆',
    mode: 'research',
    sort_order: id,
    use_count: 0,
    last_used_at: null,
    created_at: '2026-10-31T00:00:00',
  };
}

const systemPrompts = getResearchStarterPrompts('RELIANCE', 'NSE');

type EmptyProps = React.ComponentProps<typeof EmptyChatState>;

function renderEmpty(overrides: Partial<EmptyProps> = {}) {
  const props: EmptyProps = {
    sessionMode: 'research',
    symbol: 'RELIANCE',
    exchange: 'NSE',
    systemPrompts,
    isStreaming: false,
    onLaunchPrompt: vi.fn(),
    userPrompts: [1, 2, 3, 4].map((n) => makePrompt(n, `My Prompt ${n}`)),
    promptsLoading: false,
    promptsTotal: 4,
    promptsPage: 0,
    promptsHasMore: false,
    onCreatePrompt: vi.fn(),
    onEditPrompt: vi.fn(),
    onDeletePrompt: vi.fn(),
    onDuplicateSystemPrompt: vi.fn(),
    armedWorkflows: 0,
    nextRunAt: null,
    onPageChange: vi.fn(),
    ...overrides,
  };
  render(<EmptyChatState {...props} />);
  return props;
}

describe('AiChatStarterViews / EmptyChatState', () => {
  it('renders the four built-in system prompts as read-only SYS cards', () => {
    renderEmpty();
    expect(screen.getByText('SYSTEM PROMPTS')).toBeInTheDocument();
    expect(screen.getAllByText('SYS')).toHaveLength(4);
    for (const prompt of systemPrompts) {
      expect(screen.getByText(prompt.title)).toBeInTheDocument();
    }
  });

  it('renders one page of four saved user prompts', () => {
    renderEmpty();
    expect(screen.getByText('MY PROMPTS')).toBeInTheDocument();
    for (let n = 1; n <= 4; n += 1) {
      expect(screen.getByText(`My Prompt ${n}`)).toBeInTheDocument();
    }
  });

  it('hides pagination when four or fewer prompts exist', () => {
    renderEmpty({ promptsTotal: 4 });
    expect(screen.queryByText(/Showing \d/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Next page')).not.toBeInTheDocument();
  });

  it('shows the range and pages saved prompts four at a time', () => {
    const onPageChange = vi.fn();
    renderEmpty({ promptsTotal: 12, onPageChange });

    expect(screen.getByText(/Showing 1.4 of 12/)).toBeInTheDocument();
    expect(screen.getByLabelText('Previous page')).toBeDisabled();

    fireEvent.click(screen.getByLabelText('Next page'));
    expect(onPageChange).toHaveBeenCalledWith(1);

    fireEvent.click(screen.getByRole('button', { name: '3' }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it('launches a system prompt with a single click', () => {
    const props = renderEmpty();
    fireEvent.click(screen.getByText(systemPrompts[0].title));
    expect(props.onLaunchPrompt).toHaveBeenCalledWith(systemPrompts[0].prompt);
  });

  it('launches a saved user prompt with its stored instruction', () => {
    const props = renderEmpty();
    fireEvent.click(screen.getByText('My Prompt 2'));
    expect(props.onLaunchPrompt).toHaveBeenCalledWith('Instruction for My Prompt 2');
  });

  it('opens an inline editor and saves an edited saved prompt', () => {
    const props = renderEmpty();

    fireEvent.click(screen.getAllByLabelText('Edit')[0]);
    expect(screen.getByText('EDIT PROMPT')).toBeInTheDocument();

    const editor = document.querySelector('textarea');
    expect(editor).not.toBeNull();
    fireEvent.change(editor as HTMLTextAreaElement, {
      target: { value: 'Rewritten instruction' },
    });

    fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

    expect(props.onEditPrompt).toHaveBeenCalledTimes(1);
    expect(props.onEditPrompt).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1, prompt: 'Rewritten instruction' }),
    );
  });

  it('duplicates a system prompt into the saved list', () => {
    const props = renderEmpty();
    fireEvent.click(screen.getAllByLabelText('Duplicate to my prompts')[0]);
    expect(props.onDuplicateSystemPrompt).toHaveBeenCalledWith(systemPrompts[0]);
  });
});
