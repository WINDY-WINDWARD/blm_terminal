import { describe, expect, it, vi, beforeEach } from 'vitest';
import { driver } from 'driver.js';
import { TourGuide } from '@/components/tutorial/TourGuide';
import { FirstLaunchModal } from '@/components/modals/FirstLaunchModal';
import { onboardingCompletedAtom, tutorialStatusAtom } from '@/store/terminalStore';
import { render, screen, act } from '@/__tests__/utils/renderWithProviders';

vi.mock('driver.js', () => ({
  driver: vi.fn(() => ({ drive: vi.fn(), destroy: vi.fn() })),
}));

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
  it('shows the wizard when onboarding is incomplete', () => {
    render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, false]] },
    });
    expect(screen.getByText('FIRST-TIME SETUP · STEP 1 OF 7')).toBeInTheDocument();
    expect(screen.getByText('Welcome to BLM Terminal.')).toBeInTheDocument();
  });

  it('hides the wizard once onboarding is completed', () => {
    const { container } = render(<FirstLaunchModal />, {
      wrapperProps: { initialAtomValues: [[onboardingCompletedAtom, true]] },
    });
    expect(container.innerHTML).toBe('');
  });
});
