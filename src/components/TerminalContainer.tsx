'use client';

import React, { useEffect } from 'react';
import { useAtom, useSetAtom } from 'jotai';
import { activeCommandAtom, activePanelsAtom, focusedPanelAtom } from '@/store/terminalStore';

export function TerminalContainer({ children }: { children: React.ReactNode }) {
    const [activeCommand, setActiveCommand] = useAtom(activeCommandAtom);
    const [activePanels, setActivePanels] = useAtom(activePanelsAtom);
    const [focusedPanel] = useAtom(focusedPanelAtom);

    // Keyboard shortcut listener
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            // Focus command bar on 'Escape' or '/'
            if (e.key === 'Escape' || e.key === '/') {
                e.preventDefault();
                const input = document.getElementById('terminal-command-input');
                if (input) {
                    input.focus();
                }
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);

    // Command Processor: Apply new command to the focused panel
    useEffect(() => {
        if (activeCommand) {
            const validWidgets = ['TOP', 'POS', 'ORDER', 'CHART', 'WATCH'];
            if (validWidgets.includes(activeCommand)) {
                setActivePanels(prev => ({
                    ...prev,
                    [focusedPanel]: activeCommand
                }));
            }
            // Reset active command immediately after processing
            setActiveCommand('');
        }
    }, [activeCommand, focusedPanel, setActivePanels, setActiveCommand]);

    return (
        <main className="flex flex-col h-screen w-screen bg-terminal-bg text-terminal-amber overflow-hidden">
            {children}
        </main>
    );
}
