import type { WidgetTourDefinition } from '../types';

export const newsTour: WidgetTourDefinition = {
  command: 'NEWS',
  title: 'News & Wire Feed',
  steps: [
    {
      id: 'news-source-filters',
      anchor: 'news-source-filters',
      title: 'Source Filters',
      body: 'Filter dispatches across primary wire feeds or toggle the full 38-feed network. Click ALL to reset source filtering.',
    },
    {
      id: 'news-filter-bar',
      anchor: 'news-filter-bar',
      title: 'Sentiment & Search',
      body: 'Filter headlines by BULLISH, BEARISH, or NEUTRAL sentiment. Type in the search box to find specific tickers and keywords.',
    },
    {
      id: 'news-feed-list',
      anchor: 'news-feed-list',
      title: 'Multi-Stream Wire Feed',
      body: 'Scan incoming headlines in real time with source tags, publication age, and threat levels. Click any article to read it inside the terminal.',
    },
    {
      id: 'news-entity-chips',
      anchor: 'news-entity-chips',
      title: 'Entity Chips',
      body: 'Inspect extracted tickers, organizations, people, and countries. Click any ticker chip to set the active terminal symbol.',
    },
    {
      id: 'news-pagination',
      anchor: 'news-pagination',
      title: 'Feed Pagination',
      body: 'Navigate through historical wire dispatches fifty records at a time. To replay this tour, open DOCS with DOCS and NEWS both open.',
    },
  ],
};
