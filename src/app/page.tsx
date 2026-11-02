import { TerminalContainer } from '@/components/TerminalContainer';
import { CommandBar } from '@/components/CommandBar';
import { GridSystem } from '@/components/GridSystem';
import { TickerBar } from '@/components/TickerBar';
import { AuthGuard } from '@/components/AuthGuard';
import { WidgetTourController } from '@/components/widgetTour/WidgetTourController';

export default function Home() {
  return (
    <TerminalContainer>
      <AuthGuard>
        <WidgetTourController surface="grid" />
        <CommandBar />
        <GridSystem />
        <TickerBar />
      </AuthGuard>
    </TerminalContainer>
  );
}
