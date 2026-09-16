// iinvest.cogencis.com typed wrapper for the FDM widget and NewsWidget.
//
// Mirrors the same proxy convention as other lib files: hit /api/py/iinvest/*
// and let the Next.js catch-all proxy forward to the FastAPI backend.
//
// The FDM widget's 13 collapsible sections consume these typed helpers.
// The NewsWidget's "Source:" selector uses fetchIinvestNews.

export interface IinvestHealth {
  configured: boolean;
  healthy: boolean;
  expires_at: string | null;
  last_error: string | null;
}

export interface IinvestPath {
  symbol: string;
  isin: string;
  path: string;
}

export interface IinvestResponse<T = unknown> {
  status: boolean;
  message: string;
  response: {
    pagingInfo?: { pageNo: number; pageSize: number; total: number };
    columns?: Array<{
      field: string;
      displayName: string;
      dataType: string;
      format?: string;
      action?: string;
    }>;
    data?: T[];
  };
}

export interface IinvestShareholderRow {
  ID?: string | number;
  ParentID?: string | number;
  IsExpanded?: boolean;
  Description: string;
  [quarter: string]: string | number | boolean | undefined;
}

export interface IinvestAnnouncementRow {
  f_156?: string;
  f_158?: string;
  f_159?: string;
  f_25008?: string;
  isin?: string;
  exchangesymbol?: string;
  xEx_Date?: string;
  xPurpose?: string;
}

export interface IinvestInsiderRow {
  f_28?: string;
  f_4?: string;
  f_5?: string;
  // Numeric fields are typed as string | number because the iinvest API
  // sometimes returns them as numeric strings (e.g. "19010") and sometimes
  // as actual numbers. We coerce to number in the mapper.
  f_7?: string | number;
  f_8?: string | number;
  f_10?: string | number;
  f_12?: string;
  f_14?: string | number;
  f_15?: string | number;
  f_19?: string;
  f_25008?: string;
}

export interface IinvestTimeseriesRow {
  date: string;
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IinvestTimeseriesResponse {
  status: boolean;
  response: {
    snapshot: {
      yearHigh?: number;
      yearLow?: number;
      lastPrice?: number;
    };
    data: IinvestTimeseriesRow[];
  };
}

async function _get<T>(path: string, timeoutMs = 60000): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`/api/py${path}`, { signal: ctrl.signal });
    if (!res.ok) {
      const err = new Error(`iinvest ${res.status}`) as Error & { status: number };
      err.status = res.status;
      throw err;
    }
    return res.json() as Promise<T>;
  } finally {
    clearTimeout(t);
  }
}

export async function fetchIinvestHealth(): Promise<IinvestHealth> {
  return _get<IinvestHealth>('/iinvest/health', 5000);
}

export async function fetchIinvestPath(symbol: string): Promise<IinvestPath> {
  return _get<IinvestPath>(`/iinvest/path/${encodeURIComponent(symbol)}`, 60000);
}

export async function fetchIinvestAnnouncements(symbol: string): Promise<IinvestResponse<IinvestAnnouncementRow>> {
  return _get(`/iinvest/announcements/${encodeURIComponent(symbol)}`);
}

export async function fetchIinvestInsiderTrading(symbol: string): Promise<IinvestResponse<IinvestInsiderRow>> {
  return _get(`/iinvest/insider-trading/${encodeURIComponent(symbol)}`);
}

export async function fetchIinvestKeyShareholders(symbol: string): Promise<{ status: boolean; response: { data: IinvestShareholderRow[] } }> {
  return _get(`/iinvest/key-shareholders/${encodeURIComponent(symbol)}`);
}

export async function fetchIinvestCorporateActions(symbol: string, actionType: string): Promise<IinvestResponse> {
  return _get(`/iinvest/corporate-actions/${encodeURIComponent(symbol)}?action_type=${actionType}`);
}

export async function fetchIinvestBoardMeetings(symbol: string): Promise<IinvestResponse> {
  return _get(`/iinvest/board-meetings/${encodeURIComponent(symbol)}`);
}

export async function fetchIinvestPledgedShares(symbol: string): Promise<IinvestResponse<Record<string, unknown>>> {
  return _get(`/iinvest/pledged-shares/${encodeURIComponent(symbol)}`);
}

export async function fetchIinvestBlockDeals(symbol: string): Promise<IinvestResponse<Record<string, unknown>>> {
  return _get(`/iinvest/block-deals/${encodeURIComponent(symbol)}`);
}

export async function fetchIinvestBulkDeals(symbol: string): Promise<IinvestResponse<Record<string, unknown>>> {
  return _get(`/iinvest/bulk-deals/${encodeURIComponent(symbol)}`);
}

export async function fetchIinvestLegalCases(symbol: string): Promise<IinvestResponse> {
  return _get(`/iinvest/legal-cases/${encodeURIComponent(symbol)}`);
}

export async function fetchIinvestSast(symbol: string): Promise<IinvestResponse> {
  return _get(`/iinvest/sast/${encodeURIComponent(symbol)}`);
}

export async function fetchIinvestCapitalHistory(symbol: string): Promise<IinvestResponse> {
  return _get(`/iinvest/capital-history/${encodeURIComponent(symbol)}`);
}

export async function fetchIinvestTimeseries(symbol: string, from = "1DAY"): Promise<IinvestTimeseriesResponse> {
  return _get(`/iinvest/marketdata-timeseries/${encodeURIComponent(symbol)}?from=${from}`);
}

export async function fetchIinvestNews(symbol: string, limit = 20): Promise<IinvestResponse> {
  return _get(`/iinvest/news/${encodeURIComponent(symbol)}?limit=${limit}`);
}

// ── NSE market ratios (screener fallback) ─────────────────────────────────────

export interface NseMarketRatios {
  symbol: string;
  company_name: string | null;
  isin: string | null;
  symbol_pe: number | null;
  sector_pe: number | null;
  industry: string | null;
  high_52w: number | null;
  low_52w: number | null;
  high_52w_date: string | null;
  low_52w_date: string | null;
  source: string;
}

export async function fetchNseMarketRatios(symbol: string): Promise<NseMarketRatios> {
  return _get<NseMarketRatios>(`/stockuniverse/${encodeURIComponent(symbol)}/ratios`, 8000);
}

// ── All-in-one aggregator ────────────────────────────────────────────────────

export interface IinvestAllResponse {
  announcements?: IinvestResponse<IinvestAnnouncementRow>;
  auditors?: IinvestResponse;
  block_deals?: IinvestResponse<Record<string, unknown>>;
  bulk_deals?: IinvestResponse<Record<string, unknown>>;
  board_meetings?: IinvestResponse;
  capital_history?: IinvestResponse;
  corporate_actions_dividend?: IinvestResponse;
  corporate_actions_split?: IinvestResponse;
  corporate_actions_bonus?: IinvestResponse;
  corporate_actions_others?: IinvestResponse;
  financial_peer_filters?: IinvestResponse;
  index_of_charges?: IinvestResponse;
  insider_trading?: IinvestResponse<IinvestInsiderRow>;
  key_shareholders?: { status: boolean; response: { data?: IinvestShareholderRow[] } };
  legal_cases?: IinvestResponse;
  pledged_shares?: IinvestResponse<Record<string, unknown>>;
  sast?: IinvestResponse;
  tribunals?: IinvestResponse;
  news?: IinvestResponse;
  [key: string]: unknown;
}

export async function fetchIinvestAll(symbol: string): Promise<IinvestAllResponse> {
  return _get<IinvestAllResponse>(`/iinvest/all/${encodeURIComponent(symbol)}`, 60000);
}

