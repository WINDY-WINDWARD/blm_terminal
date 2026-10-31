import type { DocField, WidgetDoc } from '../types';

export const aiDoc: WidgetDoc = {
  command: 'AI',
  title: 'AI Chat',
  summary:
    'Conversational research assistant and quantitative script generator with live NSE tool access, scheduled workflows, saved launch prompts, and indicator handoff.',
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
        '⏱ Workflows: opens the right drawer with scheduled workflows and the run inbox. The badge shows unread runs.',
        '＋ in the workflows drawer: opens the NEW WORKFLOW dialog. Ask copilot describes the workflow in one sentence, or set it up manually.',
        'Model selector: selects the language model for the current conversation.',
        'CTX badge: displays the active symbol and exchange context. Check this badge before asking questions.',
        'Research / Script mode switch: toggles between question answering and indicator code generation.',
        '+ New button: creates a new scratch session in the active mode.',
        'Starter prompt cards: click any preset card in an empty session to launch common valuation or script requests.',
        'System prompt cards: four built-in prompts. Click Launch to run one. Click Duplicate to copy it into My Prompts and edit the copy.',
        'My prompt cards: your saved prompts, four per page. Use the ‹ › buttons to page. Click Launch to run one. Hover a card to edit or delete it.',
        '+ New prompt: describe what you want. The AI writes a structured prompt card and saves it to My Prompts.',
        'Workflow card buttons: Run now starts the workflow, Open shows the schedule, Edit changes the prompt, and Undo deletes it.',
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
          desc: 'Two prompt sections appear when a conversation has no messages: four read-only system prompts, and your saved prompts with four cards per page.',
        },
        {
          name: 'WORKFLOWS DRAWER',
          desc: 'Right drawer with two tabs. SCHEDULED lists workflows with status, next run, and catch-up window. INBOX lists finished runs with the trigger type.',
        },
        {
          name: 'WORKFLOW DIALOG',
          desc: 'Two tabs when creating. ASK COPILOT turns one sentence into a name, prompt, and schedule. SET UP MANUALLY edits the same fields directly. Saving asks the server for the next three run times before you confirm.',
        },
        {
          name: 'WORKFLOW CARD',
          desc: 'Chat card shown after the AI creates or edits a workflow. It shows the schedule, symbols, and the next run time.',
        },
        {
          name: 'RUN BANNER',
          desc: 'Strip above the messages when you open a workflow run. It shows the workflow name and how the run started: schedule, catch-up, or manual.',
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
        'Market data tools query live quotes, fundamentals, deals, and corporate filings on request. The widget saves sessions, attached documents, and workflow runs in local SQLite storage. Scheduled runs use read-only tools unless you enable Allow actions on the workflow. A missed run starts on the next app launch inside the catch-up window. LLM output can be wrong, so verify before trading. Never trade on unverified generative metrics.',
    },
    {
      heading: 'Guided tour',
      body:
        'The guided tour covers five key areas: 1) Command Toolbar & Context, 2) Scheduled Workflows, 3) Research & Script Modes, 4) Analyst Personas, and 5) Prompt Input & File Uploads. To replay the tour, open DOCS in another panel, keep this AI panel open, then click REPLAY TOUR.',
    },
  ],
};
