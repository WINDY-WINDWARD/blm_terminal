import React, { Suspense, act } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "../utils/renderWithProviders";
import PopoutWidgetPage from "@/app/widget/[widgetType]/page";
import { showSettingsModalAtom } from "@/store/terminalStore";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/components/WidgetRenderer", () => ({
  WidgetRenderer: () => <div data-testid="mock-widget">Mock Widget</div>,
}));

describe("PopoutWidgetPage SettingsModal mounting", () => {
  it("does not render SettingsModal when showSettingsModalAtom is false", async () => {
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
  });
});
