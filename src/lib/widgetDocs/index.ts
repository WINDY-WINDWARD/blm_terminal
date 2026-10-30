import type { WidgetDoc } from './types';
import { topDoc } from './definitions/top';
import { watchDoc } from './definitions/watch';
import { chartDoc } from './definitions/chart';
import { orderDoc } from './definitions/order';
import { posDoc } from './definitions/pos';
import { companyDoc } from './definitions/company';
import { largedealsDoc } from './definitions/largedeals';
import { breakoutsDoc } from './definitions/breakouts';
import { newsDoc } from './definitions/news';
import { analysisDoc } from './definitions/analysis';
import { notifDoc } from './definitions/notif';
import { scanDoc } from './definitions/scan';
import { anncDoc } from './definitions/annc';
import { screenerDoc } from './definitions/screener';
import { aiDoc } from './definitions/ai';
import { picksDoc } from './definitions/picks';
import { portfolioDoc } from './definitions/portfolio';
import { docsDoc } from './definitions/docs';
import { adminDoc } from './definitions/admin';
import { settingsDoc } from './definitions/settings';

export { TRIGGER_TYPE_DOCS } from './definitions/triggerTypes';

const ALL_DOCS: WidgetDoc[] = [
  topDoc,
  watchDoc,
  chartDoc,
  orderDoc,
  posDoc,
  companyDoc,
  largedealsDoc,
  breakoutsDoc,
  newsDoc,
  analysisDoc,
  notifDoc,
  scanDoc,
  anncDoc,
  screenerDoc,
  aiDoc,
  picksDoc,
  portfolioDoc,
  docsDoc,
  adminDoc,
  settingsDoc,
];

export const DOCS_INDEX: WidgetDoc[] = [...ALL_DOCS].sort((a, b) => {
  if (a.order !== b.order) {
    return a.order - b.order;
  }
  return a.command.localeCompare(b.command);
});

export const WIDGET_DOCS: Record<string, WidgetDoc> = Object.fromEntries(
  DOCS_INDEX.map((d) => [d.command, d]),
);
