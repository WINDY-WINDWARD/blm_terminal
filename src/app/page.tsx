import { TerminalContainer } from '@/components/TerminalContainer';
import { CommandBar } from '@/components/CommandBar';
import { GridSystem } from '@/components/GridSystem';
import { AuthGuard } from '@/components/AuthGuard';

export default function Home() {
  return (
    <TerminalContainer>
      <AuthGuard>
        <CommandBar />
        <GridSystem />
      </AuthGuard>
    </TerminalContainer>
  );
}
