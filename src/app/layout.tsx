import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { NotifAlertModal } from "@/components/NotifAlertModal";
import { LayoutToast } from "@/components/LayoutToast";
import { UpdateModal } from "@/components/UpdateModal";

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
        </Providers>
      </body>
    </html>
  );
}
