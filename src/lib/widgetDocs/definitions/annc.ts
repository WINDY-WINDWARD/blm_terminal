import type { DocField, WidgetDoc } from '../types';

export const anncDoc: WidgetDoc = {
  command: 'ANNC',
  title: 'Announcements',
  summary:
    'NSE corporate announcements feed: board meetings, dividends, AGMs, and regulatory filings.',
  kind: 'panel',
  order: 130,
  screenshot: {
    src: '/docs/widgets/ANNC.png',
    alt: 'Announcements widget screenshot',
    caption: 'NSE corporate announcements feed, event calendar schedule, and filing links in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A dedicated filing monitor for official NSE corporate announcements and event calendar entries. It displays upcoming board meetings, dividend declarations, quarterly results, corporate actions, and regulatory disclosures with direct access to official exchange attachments.',
    },
    {
      heading: 'Controls',
      items: [
        {
          name: 'Category tabs',
          desc: 'Select RESULTS, ALL, CORP ACTION, BOARD, or AGM/EGM. The widget opens on RESULTS by default. The count shows total records in the selected view.',
        },
        {
          name: 'Search input',
          desc: 'Filters announcements and event calendar entries in real time by company name, description, or subject text.',
        },
        {
          name: 'Clear search button',
          desc: 'Resets the search query filter immediately.',
        },
        {
          name: 'Refresh button',
          desc: 'Refetches corporate announcements and event calendar records on demand from the exchange backend.',
        },
        {
          name: 'Announcement row click',
          desc: 'Opens XML links in the in-app filing viewer. Opens other attachments in the in-app reader. Press Ctrl+Click or Cmd+Click to open in the system browser.',
        },
      ] as DocField[],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'TIME (HH:mm)',
          desc: 'Timestamp when the exchange received and published the filing during the session.',
        },
        {
          name: 'COMPANY NAME / SYMBOL',
          desc: 'Company title or exchange ticker. Amber text indicates the stock is unmonitored. White text indicates the stock is present on your watchlist.',
        },
        {
          name: 'GOLD STAR (★)',
          desc: 'Personal relevance indicator showing that the stock is currently saved in one of your watchlists.',
        },
        {
          name: 'SUBJECT BADGE',
          desc: 'Topic classification of the filing. Green denotes financial results, blue denotes board or management changes, orange denotes corporate actions or restructuring, and purple denotes shareholder meetings.',
        },
        {
          name: 'DESCRIPTION',
          desc: 'Summary narrative of the disclosed filing or the stated business agenda.',
        },
        {
          name: 'XML BADGE',
          desc: 'Indicates that the primary source XBRL or XML filing document is attached for detailed review.',
        },
        {
          name: 'UPCOMING SECTION',
          desc: 'Forward-looking schedule of planned board meetings and catalyst agendas that have not yet occurred.',
        },
        {
          name: 'ANNOUNCED SECTION',
          desc: 'Historical list of official corporate filings and results that have already been published by the exchange.',
        },
        {
          name: 'PURPOSE BADGE',
          desc: 'Specific agenda for an upcoming board meeting, such as financial results in green or dividend declarations in purple.',
        },
        {
          name: 'SME TAG',
          desc: 'Identifies securities listed on the NSE SME exchange segment, which generally have lower liquidity than mainboard listings.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'Announcements sync automatically every 5 minutes and the event calendar syncs every 15 minutes. The header displays the last sync time. Upcoming board meetings rely on prior exchange notices, while the Announced section populates once companies release their official disclosures.',
    },
    {
      heading: 'Guided tour',
      body: 'The tour has 5 steps and switches tabs as it explains them: 1) the five categories, kept on RESULTS, 2) the Upcoming and Announced split, 3) the CORP ACTION tab, 4) search, and 5) the filing list, which it returns to RESULTS for. It restores the tab that was active before the tour. To replay it, open DOCS in another panel, keep this ANNC panel open, then click REPLAY TOUR.',
    },
  ],
};

