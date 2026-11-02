import type { WidgetTourDefinition } from '../types';

export const aiTour: WidgetTourDefinition = {
  command: 'AI',
  title: 'AI Chat',
  steps: [
    {
      id: 'ai-command-toolbar',
      anchor: 'ai-toolbar',
      title: 'Command Toolbar & Context',
      body: 'Manage sessions, choose models, view streaming status, and check the CTX stock badge. The CTX badge grounds model responses.',
    },
    {
      id: 'ai-mode-toggle',
      anchor: 'ai-mode-toggle',
      title: 'Research & Script Modes',
      body: 'Toggle between Research and Script modes. Research answers analytical questions. Script mode writes chart code that you must review before Accept.',
    },
    {
      id: 'ai-persona-selection',
      anchor: 'ai-personas',
      title: 'Analyst Personas',
      body: 'Select Value, Earnings, F&O, or Macro Analyst lenses. Personas alter the analytical framework, not the underlying market facts.',
    },
    {
      id: 'ai-prompt-input',
      anchor: 'ai-input',
      title: 'Prompt Input & File Uploads',
      body: 'Submit queries, upload documents, and control generation. Model outputs can be wrong, so verify before trading. You can replay this tour from DOCS with both panels open.',
    },
  ],
};
