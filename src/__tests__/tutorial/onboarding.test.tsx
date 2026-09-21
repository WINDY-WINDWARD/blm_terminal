import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { driver } from 'driver.js';
import { TourGuide } from '@/components/tutorial/TourGuide';
import { FirstLaunchModal } from '@/components/modals/FirstLaunchModal';
import { onboardingCompletedAtom, tutorialStatusAtom } from '@/store/terminalStore';
import { getFirstBootStatus } from '@/lib/onboarding';
import { render, screen, act, waitFor } from '@/__tests__/utils/renderWithProviders';

vi.mock('driver.js', () => ({
  driver: vi.fn(() => ({ drive: vi.fn(), destroy: vi.fn() })),
}));

vi.mock('@/lib/onboarding', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/onboarding')>();
  return { ...actual, getFirstBootStatus: vi.fn() };
});

const mockedGetFirstBootStatus = vi.mocked(getFirstBootStatus);

const mockedDriver = vi.mocked(driver);

describe('TourGuide', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  it('renders nothing and does not start the tour when pending', () => {
    const { container } = render(<TourGuide />, {
      wrapperProps: { initialAtomValues: [[tutorialStatusAtom, 'pending']] },
    });
    expect(container.innerHTML).toBe('');
    expect(mockedDriver).not.toHaveBeenCalled();
  });

  it('starts the driver tour when status becomes active', () => {
    render(<TourGuide />, {
      wrapperProps: { initialAtomValues: [[tutorialStatusAtom, 'active']] },
    });
    act(() => {
      vi.runAllTimers();
    });
    expect(mockedDriver).toHaveBeenCalledTimes(1);
    const config = mockedDriver.mock.calls[0]?.[0];
    expect(config?.showProgress).toBe(true);
    expect(config?.skipMissingElement).toBe(true);
    expect(Array.isArray(config?.steps)).toBe(true);
    expect(config?.steps?.length).toBeGreaterThan(0);
  });
});

describe('FirstLaunchModal gating', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows a loader while the backend flag is unread', () => {
    mockedGetFirstBootStatus.mockReturnValue(new Promise(() => {}));
    render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, false]] },
    });
    expect(screen.getByText('Reading setup state…')).toBeInTheDocument();
    expect(screen.queryByText('FIRST-TIME SETUP · STEP 1 OF 7')).not.toBeInTheDocument();
  });

  it('shows the wizard when the backend flag resolves false', async () => {
    mockedGetFirstBootStatus.mockResolvedValue({ reachable: true, onboardingCompleted: false });
    render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, false]] },
    });
    expect(await screen.findByText('FIRST-TIME SETUP · STEP 1 OF 7')).toBeInTheDocument();
    expect(screen.getByText('Welcome to BLM Terminal.')).toBeInTheDocument();
  });

  it('hides the wizard when the backend flag resolves true', async () => {
    mockedGetFirstBootStatus.mockResolvedValue({ reachable: true, onboardingCompleted: true });
    const { container } = render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, false]] },
    });
    await waitFor(() => {
      expect(container.innerHTML).toBe('');
    });
  });

  it('shows the wizard when the backend stays unreachable past the poll cap', async () => {
    vi.useFakeTimers();
    mockedGetFirstBootStatus.mockRejectedValue(new Error('refused'));
    render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, false]] },
    });
    expect(screen.getByText('Reading setup state…')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61 * 5000);
    });
    vi.useRealTimers();
    expect(screen.getByText('FIRST-TIME SETUP · STEP 1 OF 7')).toBeInTheDocument();
    expect(screen.queryByText('Reading setup state…')).not.toBeInTheDocument();
  });

  it('hides the wizard once onboarding is completed', () => {
    const { container } = render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, true]] },
    });
    expect(container.innerHTML).toBe('');
  });
});
