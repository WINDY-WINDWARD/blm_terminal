import { TerminalContainer } from '@/components/TerminalContainer';
import { CommandBar } from '@/components/CommandBar';
import { GridSystem } from '@/components/GridSystem';
import { LiveTicker } from '@/components/LiveTicker';
import { LoginModal } from '@/components/LoginModal';

export default function Home() {
  return (
    <TerminalContainer>
      <CommandBar />
      <GridSystem />
      <LiveTicker />
      <LoginModal />
    </TerminalContainer>
  );
}
