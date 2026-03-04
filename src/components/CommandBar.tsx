'use client';

import React, { useState } from 'react';
import { useAtom } from 'jotai';
import { activeCommandAtom } from '@/store/terminalStore';

export function CommandBar() {
    const [activeCommand, setActiveCommand] = useAtom(activeCommandAtom);
    const [inputVal, setInputVal] = useState('');

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        const cmd = inputVal.trim().toUpperCase();
        if (cmd) {
            setActiveCommand(cmd);
            setInputVal(''); // clear after executing
        }
    };

    return (
        <div className="flex items-center bg-blue-900 text-white h-8 px-2 border-b border-terminal-gray font-sans font-bold text-sm shrink-0">
            <span className="mr-2">&gt;</span>
            <form onSubmit={handleSubmit} className="flex-1 flex">
                <input
                    id="terminal-command-input"
                    type="text"
                    value={inputVal}
                    onChange={(e) => setInputVal(e.target.value)}
                    placeholder="Enter command (e.g., TOP, POS, ORDER, CHART) or '/' to focus"
                    className="bg-transparent text-white placeholder-blue-300 w-full outline-none uppercase"
                    autoComplete="off"
                />
            </form>
            <div className="ml-4 truncate">
                CMD: <span className="text-terminal-amber font-mono">{activeCommand || 'NONE'}</span>
            </div>
        </div>
    );
}
