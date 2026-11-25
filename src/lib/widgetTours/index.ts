import type { WidgetTourDefinition } from './types';
import { topTour } from './definitions/top';
import { watchTour } from './definitions/watch';
import { chartTour } from './definitions/chart';
import { orderTour } from './definitions/order';
import { posTour } from './definitions/pos';
import { companyTour } from './definitions/company';
import { largedealsTour } from './definitions/largedeals';
import { breakoutsTour } from './definitions/breakouts';
import { newsTour } from './definitions/news';
import { analysisTour } from './definitions/analysis';
import { notifTour } from './definitions/notif';
import { scanTour } from './definitions/scan';
import { anncTour } from './definitions/annc';
import { screenerTour } from './definitions/screener';
import { aiTour } from './definitions/ai';
import { portfolioTour } from './definitions/portfolio';
import { picksTour } from './definitions/picks';
import { adminTour } from './definitions/admin';
import { docsTour } from './definitions/docs';

export const WIDGET_TOUR_COMMANDS: readonly string[] = [
  'TOP',
  'WATCH',
  'CHART',
  'ORDER',
  'POS',
  'COMPANY',
  'LARGEDEALS',
  'BREAKOUTS',
  'NEWS',
  'ANALYSIS',
  'NOTIF',
  'SCAN',
  'ANNC',
  'SCREENER',
  'AI',
  'PORTFOLIO',
  'PICKS',
  'ADMIN',
  'DOCS',
] as const;

export const WIDGET_TOURS: Record<string, WidgetTourDefinition> = {
  TOP: topTour,
  WATCH: watchTour,
  CHART: chartTour,
  ORDER: orderTour,
  POS: posTour,
  COMPANY: companyTour,
  LARGEDEALS: largedealsTour,
  BREAKOUTS: breakoutsTour,
  NEWS: newsTour,
  ANALYSIS: analysisTour,
  NOTIF: notifTour,
  SCAN: scanTour,
  ANNC: anncTour,
  SCREENER: screenerTour,
  AI: aiTour,
  PORTFOLIO: portfolioTour,
  PICKS: picksTour,
  ADMIN: adminTour,
  DOCS: docsTour,
};

export function getWidgetTour(command: string): WidgetTourDefinition | undefined {
  return WIDGET_TOURS[command.toUpperCase()];
}
