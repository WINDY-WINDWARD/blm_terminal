'use client';

import React from 'react';
import { useAtomValue } from 'jotai';
import { activePanelsAtom } from '@/store/terminalStore';
import { Panel } from './Panel';

export function GridSystem() {
    const panels = useAtomValue(activePanelsAtom);

    return (
        <div className="flex-1 grid grid-cols-2 grid-rows-2 gap-[1px] bg-terminal-gray p-[1px] overflow-hidden">
            <Panel id="panel-1" title={panels['panel-1']} />
            <Panel id="panel-2" title={panels['panel-2']} />
            <Panel id="panel-3" title={panels['panel-3']} />
            <Panel id="panel-4" title={panels['panel-4']} />
        </div>
    );
}
