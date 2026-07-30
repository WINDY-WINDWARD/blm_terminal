import { TerminalContainer } from '@/components/TerminalContainer';
import { CommandBar } from '@/components/CommandBar';
import { GridSystem } from '@/components/GridSystem';
import { LoginModal } from '@/components/LoginModal';

export default function Home() {
  return (
    <TerminalContainer>
      <CommandBar />
      <GridSystem />
      <LoginModal />
    </TerminalContainer>
  );
}
