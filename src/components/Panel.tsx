'use client';

import React from 'react';
import { useAtom } from 'jotai';
import { focusedPanelAtom } from '@/store/terminalStore';
import { TopWidget } from './widgets/TopWidget';
import { PosWidget } from './widgets/PosWidget';
import { OrderWidget } from './widgets/OrderWidget';
import { ChartWidget } from './widgets/ChartWidget';
import { WatchWidget } from './widgets/WatchWidget';

interface PanelProps {
    id: string;
    title: string;
}

export function Panel({ id, title }: PanelProps) {
    const [focusedPanel, setFocusedPanel] = useAtom(focusedPanelAtom);
    const isFocused = focusedPanel === id;

    const renderWidget = () => {
        switch (title) {
            case 'TOP': return <TopWidget />;
            case 'POS': return <PosWidget />;
            case 'ORDER': return <OrderWidget />;
            case 'CHART': return <ChartWidget />;
            case 'WATCH': return <WatchWidget />;
            default:
                return (
                    <div className="text-terminal-amber/50 text-xs font-mono h-full w-full flex items-center justify-center">
                        [{title} WIDGET NOT FOUND]
                    </div>
                );
        }
    };

    return (
        <div
            className={`bg-terminal-bg border-2 flex flex-col overflow-hidden cursor-default transition-colors duration-200 ${isFocused ? 'border-blue-500' : 'border-transparent'
                }`}
            onClick={() => setFocusedPanel(id)}
        >
            <div className={`h-6 px-2 flex items-center font-bold text-xs uppercase ${isFocused ? 'bg-blue-900 text-white' : 'bg-terminal-gray text-terminal-amber'
                }`}>
                <span className="truncate">{title}</span>
            </div>
            <div className="flex-1 relative overflow-hidden p-1">
                {renderWidget()}
            </div>
        </div>
    );
}
