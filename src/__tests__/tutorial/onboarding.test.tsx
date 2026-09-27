import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { driver } from 'driver.js';
import { TourGuide } from '@/components/tutorial/TourGuide';
import { FirstLaunchModal } from '@/components/modals/FirstLaunchModal';
import { onboardingCompletedAtom, tutorialStatusAtom } from '@/store/terminalStore';
import { getFirstBootStatus, getEulaStatus, acceptEula } from '@/lib/onboarding';
import { render, screen, act, waitFor, fireEvent } from '@/__tests__/utils/renderWithProviders';

vi.mock('driver.js', () => ({
  driver: vi.fn(() => ({ drive: vi.fn(), destroy: vi.fn() })),
}));

vi.mock('@/lib/onboarding', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/onboarding')>();
  return { ...actual, getFirstBootStatus: vi.fn(), getEulaStatus: vi.fn(), acceptEula: vi.fn() };
});

const mockedGetFirstBootStatus = vi.mocked(getFirstBootStatus);
const mockedGetEulaStatus = vi.mocked(getEulaStatus);
const mockedAcceptEula = vi.mocked(acceptEula);

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
    // Default: EULA already accepted so pre-existing wizard tests keep their flow.
    mockedGetEulaStatus.mockResolvedValue({
      reachable: true,
      accepted: true,
      version: 'eula-v1',
      acceptedAt: 123,
    });
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
    expect(screen.queryByText('FIRST-TIME SETUP · STEP 1 OF 8')).not.toBeInTheDocument();
  });

  it('shows the wizard when the backend flag resolves false', async () => {
    mockedGetFirstBootStatus.mockResolvedValue({ reachable: true, onboardingCompleted: false });
    render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, false]] },
    });
    // EULA is pre-accepted in the default mock, so the wizard lands on welcome
    // (step index resolves after the async EULA poll — never pin step 1 here).
    expect(await screen.findByText('Welcome to BLM Terminal.')).toBeInTheDocument();
    expect(screen.getByText(/FIRST-TIME SETUP · STEP \d OF 8/)).toBeInTheDocument();
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
    expect(await screen.findByText('Welcome to BLM Terminal.')).toBeInTheDocument();
    expect(screen.queryByText('Reading setup state…')).not.toBeInTheDocument();
  });

  it('hides the wizard once onboarding is completed', () => {
    const { container } = render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, true]] },
    });
    expect(container.innerHTML).toBe('');
  });

  it('re-flashes the EULA when the DB says it is not accepted despite completed onboarding', async () => {
    mockedGetFirstBootStatus.mockResolvedValue({ reachable: true, onboardingCompleted: true });
    mockedGetEulaStatus.mockResolvedValue({
      reachable: true,
      accepted: false,
      version: 'eula-v1',
      acceptedAt: null,
    });
    render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, true]] },
    });
    expect(await screen.findByText('End-User License Agreement')).toBeInTheDocument();
    expect(screen.getByRole('checkbox')).not.toBeChecked();
  });

  it('blocks Continue until the EULA checkbox is checked, then records acceptance', async () => {
    mockedGetFirstBootStatus.mockResolvedValue({ reachable: true, onboardingCompleted: false });
    mockedGetEulaStatus.mockResolvedValue({
      reachable: true,
      accepted: false,
      version: 'eula-v1',
      acceptedAt: null,
    });
    mockedAcceptEula.mockResolvedValue(undefined);
    render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, false]] },
    });
    const cont = await screen.findByRole('button', { name: 'Continue' });
    expect(cont).toBeDisabled();

    fireEvent.click(screen.getByRole('checkbox'));
    expect(cont).toBeEnabled();

    fireEvent.click(cont);
    expect(await screen.findByText('Welcome to BLM Terminal.')).toBeInTheDocument();
    expect(mockedAcceptEula).toHaveBeenCalledWith('eula-v1');
  });

  it('declining the EULA quits the app via electronAPI.quitApp', async () => {
    const quitApp = vi.fn();
    (window as unknown as { electronAPI?: unknown }).electronAPI = { quitApp };
    mockedGetFirstBootStatus.mockResolvedValue({ reachable: true, onboardingCompleted: false });
    mockedGetEulaStatus.mockResolvedValue({
      reachable: true,
      accepted: false,
      version: 'eula-v1',
      acceptedAt: null,
    });
    render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, false]] },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Decline & Exit' }));
    expect(quitApp).toHaveBeenCalledTimes(1);
    delete (window as unknown as { electronAPI?: unknown }).electronAPI;
  });
});
