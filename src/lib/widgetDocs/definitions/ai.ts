import type { DocField, WidgetDoc } from '../types';

export const aiDoc: WidgetDoc = {
  command: 'AI',
  title: 'AI Chat',
  summary:
    'Conversational research assistant and quantitative script generator with live NSE tool access and indicator handoff.',
  kind: 'panel',
  order: 150,
  screenshot: {
    src: '/docs/widgets/AI.png',
    alt: 'AI Chat widget screenshot',
    caption: 'AI Chat as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body:
        'An interactive intelligence copilot and script laboratory for Indian equities. The widget executes live market tools, generates technical chart overlays, and maintains persistent conversation sessions. A command toolbar manages models and session context, while the message stream renders tool cards, analyst commentary, and code review cards. Analyst persona chips adjust analytical perspective, and an elevated input footer handles queries and document attachments.',
    },
    {
      heading: 'Controls',
      items: [
        '☰ Sessions: opens the drawer with chat history and document library management.',
        'Model selector: selects the language model for the current conversation.',
        'CTX badge: displays the active symbol and exchange context. Check this badge before asking questions.',
        'Research / Script mode switch: toggles between question answering and indicator code generation.',
        '+ New button: creates a new scratch session in the active mode.',
        'Starter prompt cards: click any preset card in an empty session to launch common valuation or script requests.',
        'Analyst persona chips: select Value, Earnings, F&O, or Macro Analyst to guide reasoning frameworks.',
        'Attachment clip (📎): attaches PDF or CSV files for document-grounded analysis.',
        'Prompt input: text area for queries or script specs. Press Enter to send, Shift+Enter for newline.',
        'Send / Stop button: transmits prompt to the agent pipeline or halts active stream generation.',
        'Accept card button: loads generated script code directly into active chart panels.',
        'Discard card button: rejects generated script code without applying it to charts.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'SESSIONS DRAWER',
          desc: 'Drawer displaying historical chats and uploaded documents. Selecting an entry loads past turns; deleting permanently removes it from storage.',
        },
        {
          name: 'MODEL SELECTOR',
          desc: 'Dropdown showing models supported by the active provider configured in Settings. Disabled while streaming.',
        },
        {
          name: 'CTX BADGE',
          desc: 'Context badge formatted as SYMBOL.EXCHANGE. Sets which stock the answer is grounded on, so check it before asking.',
        },
        {
          name: 'STREAMING STATUS',
          desc: 'Live execution banner showing thinking state, upstream route name, and elapsed generation time in seconds.',
        },
        {
          name: 'MODE SWITCH',
          desc: 'Two-way toggle between Research and Script mode. Research mode answers questions; Script mode writes chart scripts you must review before Accept.',
        },
        {
          name: 'ANALYST PERSONAS',
          desc: 'Lenses: Value Analyst (moat and safety margin), Earnings Analyst (forensics), F&O Analyst (derivatives), Macro Analyst (sector breadth). Personas change the framework, not the facts.',
        },
        {
          name: 'STARTER CARDS',
          desc: 'Four initial prompt suggestions displayed when a conversation has no messages yet.',
        },
        {
          name: 'SCRIPT CARD',
          desc: 'Interactive response card in Script mode with script name, revision number, and Accept/Discard actions.',
        },
        {
          name: 'INPUT BAR',
          desc: 'Bottom bar containing attachment pills, document upload button, prompt textarea, and Send/Stop action.',
        },
        {
          name: 'CONFIGURATION BANNER',
          desc: 'Inline warning notice displayed when no AI inference provider credentials are configured in Settings.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body:
        'Market data tools query live quotes, fundamentals, deals, and corporate filings on request. The widget saves sessions and attached documents in local SQLite storage. LLM output can be wrong, so verify before trading. Never trade on unverified generative metrics.',
    },
    {
      heading: 'Guided tour',
      body:
        'The guided tour covers four key areas: 1) Command Toolbar & Context, 2) Research & Script Modes, 3) Analyst Personas, and 4) Prompt Input & File Uploads. To replay the tour, open DOCS in another panel, keep this AI panel open, then click REPLAY TOUR.',
    },
  ],
};
