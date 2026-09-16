import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";
import "driver.js/dist/driver.css";
import "@/components/tutorial/tutorial.css";
import { Providers } from "@/components/Providers";
import { NotifAlertModal } from "@/components/NotifAlertModal";
import { LayoutToast } from "@/components/LayoutToast";
import { UpdateModal } from "@/components/UpdateModal";
import { AdvancedScrapingModal } from "@/components/modals/AdvancedScrapingModal";
import { FirstLaunchModal } from "@/components/modals/FirstLaunchModal";
import { TourGuide } from "@/components/tutorial/TourGuide";

const jetBrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "BLM Terminal",
  description: "OpenAlgo Financial Terminal",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${jetBrainsMono.variable} antialiased`}>
        <Providers>
          {children}
          <NotifAlertModal />
          <LayoutToast />
          <UpdateModal />
          <AdvancedScrapingModal />
          <FirstLaunchModal />
          <TourGuide />
        </Providers>
      </body>
    </html>
  );
}
