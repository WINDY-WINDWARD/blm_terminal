'use client';

import React from 'react';
import { WorkspaceTab } from './WorkspaceTab';
import { ConnectionsTab } from './ConnectionsTab';
import { IntelligenceTab } from './IntelligenceTab';
import { AutomationTab } from './AutomationTab';
import { SystemTab } from './SystemTab';
import type { SettingsTabId } from '@/store/terminalStore';
import type { SettingsTabPropsBundle } from './tabProps';

export interface SettingsTabRendererProps extends SettingsTabPropsBundle {
  activeTab: SettingsTabId;
}

export function SettingsTabRenderer({
  activeTab,
  workspaceProps,
  connectionsProps,
  intelligenceProps,
  automationProps,
  systemProps,
}: SettingsTabRendererProps) {
  return (
    <div key={activeTab} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2.5 max-w-full animate-in fade-in duration-200">
      {activeTab === 'workspace' && <WorkspaceTab {...workspaceProps} />}
      {activeTab === 'connections' && <ConnectionsTab {...connectionsProps} />}
      {activeTab === 'intelligence' && <IntelligenceTab {...intelligenceProps} />}
      {activeTab === 'automation' && <AutomationTab {...automationProps} />}
      {activeTab === 'system' && <SystemTab {...systemProps} />}
    </div>
  );
}
