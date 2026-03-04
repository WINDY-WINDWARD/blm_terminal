import { TerminalContainer } from '@/components/TerminalContainer';
import { CommandBar } from '@/components/CommandBar';
import { GridSystem } from '@/components/GridSystem';
import { LiveTicker } from '@/components/LiveTicker';

export default function Home() {
  return (
    <TerminalContainer>
      <CommandBar />
      <GridSystem />
      <LiveTicker />
    </TerminalContainer>
  );
}
