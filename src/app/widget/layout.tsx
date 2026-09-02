import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'BLM Widget',
};

export default function WidgetLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="w-screen h-screen overflow-hidden bg-terminal-bg text-terminal-text select-none">
      {children}
    </div>
  );
}
