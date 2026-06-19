export interface TradingViewFundamentals {
    name?: string;
    description?: string;
    close?: number;
    average_volume_10d_calc?: number;
    price_earnings_ttm?: number;
    earnings_per_share_basic_ttm?: number;
    price_revenue_ttm?: number;
    price_book_fq?: number;
    price_free_cash_flow_ttm?: number;
    dividends_yield?: number;
    dividend_payout_ratio_ttm?: number;
    gross_margin_ttm?: number;
    operating_margin_ttm?: number;
    net_margin_ttm?: number;
    return_on_assets_fq?: number;
    return_on_equity_fq?: number;
    return_on_invested_capital_fq?: number;
    debt_to_equity_fq?: number;
    current_ratio_fq?: number;
    quick_ratio_fq?: number;
    total_revenue_fq?: number;
    gross_profit_fq?: number;
    operating_income_fq?: number;
    net_income_fq?: number;
    ebitda_fq?: number;
    total_assets_fq?: number;
    total_current_assets_fq?: number;
    total_liabilities_fq?: number;
    total_current_liabilities_fq?: number;
    total_equity_fq?: number;
    cash_n_short_term_invest_fq?: number;
    cash_n_equivalents_fq?: number;
    total_debt_fq?: number;
    free_cash_flow_fq?: number;
    capital_expenditures_fq?: number;
    cash_f_operating_activities_fq?: number;
    cash_f_investing_activities_fq?: number;
    cash_f_financing_activities_fq?: number;
    enterprise_value_fq?: number;
}

export async function fetchTradingViewFundamentals(symbol: string): Promise<TradingViewFundamentals | null> {
  try {
    const res = await fetch(`/api/py/tradingview/fundamentals/${symbol}`);
    if (!res.ok) return null;
    const json = await res.json();
    if (json && json.status && json.data && Object.keys(json.data).length > 0) {
      return json.data;
    }
    return null;
  } catch (error) {
    console.error('TradingView fundamentals fetch error:', error);
    return null;
  }
}
