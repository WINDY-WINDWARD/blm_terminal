import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import "../globals.css";

const jetBrainsMono = { variable: "font-mono" };

export const metadata: Metadata = {
  title: "BLM Logs",
  description: "Backend log viewer",
};

export default function LogsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${jetBrainsMono.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
