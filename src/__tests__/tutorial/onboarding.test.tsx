import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { driver } from 'driver.js';
import { TourGuide } from '@/components/tutorial/TourGuide';
import { FirstLaunchModal } from '@/components/modals/FirstLaunchModal';
import { AiProvidersModalHost } from '@/components/modals/AiProvidersModalHost';
import { onboardingCompletedAtom, showAiProvidersModalAtom, tutorialStatusAtom } from '@/store/terminalStore';
import { getFirstBootStatus, getEulaStatus, acceptEula, checkAiStatus } from '@/lib/onboarding';
import { render, screen, act, waitFor, fireEvent } from '@/__tests__/utils/renderWithProviders';
import { http, HttpResponse } from 'msw';
import { server } from '@/__tests__/mocks/msw-server';

vi.mock('driver.js', () => ({
  driver: vi.fn(() => ({ drive: vi.fn(), destroy: vi.fn() })),
}));

vi.mock('@/lib/onboarding', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/onboarding')>();
  return { ...actual, getFirstBootStatus: vi.fn(), getEulaStatus: vi.fn(), acceptEula: vi.fn(), checkAiStatus: vi.fn() };
});

const mockedGetFirstBootStatus = vi.mocked(getFirstBootStatus);
const mockedGetEulaStatus = vi.mocked(getEulaStatus);
const mockedAcceptEula = vi.mocked(acceptEula);
const mockedCheckAiStatus = vi.mocked(checkAiStatus);

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

  it('stays hidden when completed and the EULA poll exhausts unreachable (2026-09-28 loop)', async () => {
    vi.useFakeTimers();
    mockedGetFirstBootStatus.mockResolvedValue({ reachable: true, onboardingCompleted: true });
    mockedGetEulaStatus.mockRejectedValue(new Error('404'));
    const { container } = render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, true]] },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61 * 5000);
    });
    vi.useRealTimers();
    expect(container.innerHTML).toBe('');
    expect(screen.queryByText('End-User License Agreement')).not.toBeInTheDocument();
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

  it('declining the EULA quits the app via electronAPI.quitApp', async () => {    const quitApp = vi.fn();
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

  it('shows the setup-video link on the welcome step (opens externally)', async () => {
    mockedGetFirstBootStatus.mockResolvedValue({ reachable: true, onboardingCompleted: false });
    render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, false]] },
    });
    expect(await screen.findByText('Welcome to BLM Terminal.')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /setup video/i });
    expect(link).toHaveAttribute('href', 'https://youtu.be/wmbhDGowNbM');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('uses provider management instead of a legacy provider or key field during onboarding', async () => {
    mockedGetFirstBootStatus.mockResolvedValue({ reachable: true, onboardingCompleted: false });
    mockedCheckAiStatus.mockResolvedValue({ provider: 'antigravity', isConfigured: false });
    render(<FirstLaunchModal initialStep="ai" />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, false]] },
    });

    expect(await screen.findByText('AI assistant (optional)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /OPEN PROVIDER MANAGER/i })).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/sk-/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Login with Google|Sign in with ChatGPT/i })).not.toBeInTheDocument();
  });

  it('keeps the AI step open and refreshes status when the provider manager closes', async () => {
    mockedGetFirstBootStatus.mockResolvedValue({ reachable: true, onboardingCompleted: false });
    mockedCheckAiStatus
      .mockResolvedValueOnce({ provider: 'antigravity', isConfigured: false })
      .mockResolvedValueOnce({ provider: 'antigravity', isConfigured: true });
    server.use(
      http.get('/api/py/ai/routes', () => HttpResponse.json({
        routes: [],
        active_route_id: '',
        proxy_status: { state: 'stopped', pid: null, port: null, uptime_seconds: 0, restart_count: 0 },
        vault_state: 'available',
        recovery_state: null,
        settings: { strategy: 'priority', session_affinity: false, session_affinity_ttl: '1h', request_retry: 0, max_retry_credentials: 1, max_retry_interval: 0 },
      })),
    );

    render(
      <>
        <FirstLaunchModal initialStep="ai" />
        <AiProvidersModalHost />
      </>,
      {
        wrapperProps: {
          initialAtomValues: [
            [onboardingCompletedAtom, false],
            [showAiProvidersModalAtom, false],
          ],
        },
      }
    );

    expect(await screen.findByText('Status: not configured')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /OPEN PROVIDER MANAGER/i }));
    expect(await screen.findByText(/AI PROVIDER ROUTES & OAUTH MANAGER/i)).toBeInTheDocument();
    expect(screen.getByText('AI assistant (optional)')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Close AI providers modal/i }));
    await waitFor(() => expect(screen.getByText('Status: connected')).toBeInTheDocument());
    expect(mockedCheckAiStatus).toHaveBeenCalledTimes(2);
  });
});
