import type { DocField, WidgetDoc } from '../types';

export const docsDoc: WidgetDoc = {
  command: 'DOCS',
  title: 'Documentation & Tour Replay',
  summary:
    'Reference for every widget, with screenshots, field meanings, and per-widget tour replay.',
  kind: 'panel',
  order: 180,
  screenshot: {
    src: '/docs/widgets/DOCS.png',
    alt: 'Documentation widget screenshot',
    caption: 'Documentation as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A reference page for each terminal widget. By default the page follows the focused panel. When DOCS itself has focus, the widget shows the full index instead. Each page carries a screenshot taken from the running terminal, the controls, and the meaning of each field.',
    },
    {
      heading: 'Controls',
      items: [
        'Focus behaviour: focus any non-DOCS panel and its page loads automatically, marked (auto). Focus DOCS or an empty panel to return to the index.',
        'Index row: click the summary text of a row to open that widget page and stop the auto-follow until you click INDEX.',
        '← INDEX: clears the manual page selection and returns to the full widget list.',
        '▸ APP TOUR: replays the whole-terminal welcome tour, including layout, command bar, and panel basics.',
        '▸ REPLAY TOUR: replays the tour for the widget on the open page. The widget must be open in a panel.',
        'TOUR in an index row: the same replay, started from the list.',
        'Screenshot: click the image to zoom it inside the panel. Press Escape or click again to close.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'SEEN / NOT RUN',
          desc: 'SEEN means the widget tour has already run for this account on this machine. NOT RUN means it will start automatically the next time that widget opens. The flag is stored in the local database per user, so another account starts fresh.',
        },
        {
          name: 'COMMAND',
          desc: 'The exact word to type in the command bar to open that widget in the focused panel. Examples: CHART, WATCH, NOTIF.',
        },
        {
          name: 'SUMMARY',
          desc: 'A one-line statement of what the widget is for. Read it to choose the right panel before you open the full page.',
        },
        {
          name: 'PAGE HEADER',
          desc: 'Shows the command and the full title of the open page. The line below is the summary that also appears in the index.',
        },
        {
          name: 'SCREENSHOT CAPTION',
          desc: 'Names the state shown in the image. The image comes from this build, but live prices differ from the capture. Use the image for layout, not for current values.',
        },
        {
          name: 'SECTION BLOCKS',
          desc: 'Five fixed blocks per page. What this widget shows gives the purpose. Controls lists what you can click or type. Fields and how to read them gives the meaning of each label. Data freshness and limits states the source and the delay. Guided tour gives the step count and the replay path.',
        },
        {
          name: 'OPEN HINT BANNER',
          desc: 'A red banner appears when you request a tour for a widget that is not open. It names the command to open. The layout does not change until you open that widget yourself.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'Documentation text ships with the build, so it matches that version only. Screenshots are captured from an installed build. Values inside a screenshot are a frozen moment and never update. Tour state is stored per user in the local SQLite database and mirrored to local storage, so it survives restarts but does not travel to another machine.',
    },
    {
      heading: 'Guided tour',
      body: 'The DOCS tour has 4 steps: 1) the widget reference index, 2) the CHART page it opens, 3) the screenshot and zoom, 4) the REPLAY TOUR control. It returns to the index when it ends. To replay it, keep this DOCS panel open and click TOUR on the DOCS row in the index, or click ▸ REPLAY TOUR while this page is open. A replay runs in a popped-out window when one is open. The hint covers both cases.',
    },
  ],
};
