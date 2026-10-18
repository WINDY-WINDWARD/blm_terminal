import React, { Suspense, act } from "react";
import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen } from "../utils/renderWithProviders";
import PopoutWidgetPage from "@/app/widget/[widgetType]/page";
import { showSettingsModalAtom } from "@/store/terminalStore";

const { settingsModalRenderSpy } = vi.hoisted(() => ({
  settingsModalRenderSpy: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/components/WidgetRenderer", () => ({
  WidgetRenderer: () => <div data-testid="mock-widget">Mock Widget</div>,
}));

vi.mock("@/components/modals/SettingsModal", () => ({
  SettingsModal: ({ isOpen }: { isOpen?: boolean }) => {
    settingsModalRenderSpy(isOpen);
    return isOpen ? <div>TERMINAL SETTINGS</div> : null;
  }
}));

describe("PopoutWidgetPage SettingsModal mounting", () => {
  beforeEach(() => {
    settingsModalRenderSpy.mockClear();
  });

  it("does not mount SettingsModal when showSettingsModalAtom is false", async () => {
    const params = Promise.resolve({ widgetType: "AI" });
    await act(async () => {
      render(
        <Suspense fallback={<div>Loading...</div>}>
          <PopoutWidgetPage params={params} />
        </Suspense>,
        {
          wrapperProps: {
            initialAtomValues: [
              [showSettingsModalAtom, false],
            ],
          },
        }
      );
    });

    expect(await screen.findByTestId("mock-widget")).toBeInTheDocument();
    expect(screen.queryByText(/TERMINAL SETTINGS/i)).not.toBeInTheDocument();
    expect(settingsModalRenderSpy).not.toHaveBeenCalled();
  });

  it("renders SettingsModal when showSettingsModalAtom is true in detached popout", async () => {
    const params = Promise.resolve({ widgetType: "AI" });
    await act(async () => {
      render(
        <Suspense fallback={<div>Loading...</div>}>
          <PopoutWidgetPage params={params} />
        </Suspense>,
        {
          wrapperProps: {
            initialAtomValues: [
              [showSettingsModalAtom, true],
            ],
          },
        }
      );
    });

    expect(await screen.findByTestId("mock-widget")).toBeInTheDocument();
    expect(await screen.findByText(/TERMINAL SETTINGS/i)).toBeInTheDocument();
    expect(settingsModalRenderSpy).toHaveBeenCalledWith(true);
  });
});
