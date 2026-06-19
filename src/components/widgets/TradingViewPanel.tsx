import React from 'react';
import { TradingViewFundamentals } from '@/lib/tradingview';

const formatCr = (val: number | undefined | null) => {
  if (val == null) return '—';
  return `₹${(val / 10000000).toFixed(1)}Cr`;
};

const formatPct = (val: number | undefined | null) => {
  if (val == null) return '—';
  return `${val.toFixed(2)}%`;
};

const formatNum = (val: number | undefined | null, decimals = 2, prefix = '') => {
  if (val == null) return '—';
  return prefix + val.toFixed(decimals);
};

export function TradingViewPanel({ data }: { data: TradingViewFundamentals }) {
  if (!data || Object.keys(data).length === 0) return null;

  return (
    <div className="mt-2 mb-4 flex flex-col gap-2">
      <div className="px-2 pb-1 border-b border-terminal-gray/40">
        <span className="text-[11px] text-white/80 font-bold uppercase tracking-widest">
          TradingView Snapshot (TTM/FQ)
        </span>
      </div>

      <div className="px-2 grid grid-cols-2 gap-4">
        
        {/* Valuation */}
        <div className="flex-1 min-w-0">
          <div className="text-[9px] text-white/60 uppercase tracking-widest mb-1">Valuation & Yield</div>
          <table className="w-full border-collapse">
            <tbody>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">P/E (TTM)</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatNum(data.price_earnings_ttm)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">EPS (TTM)</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatNum(data.earnings_per_share_basic_ttm, 2, '₹')}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">P/B (FQ)</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatNum(data.price_book_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Price/Sales (TTM)</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatNum(data.price_revenue_ttm)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">EV (FQ)</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatCr(data.enterprise_value_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Dividend Yield</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatPct(data.dividends_yield)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Payout Ratio</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatPct(data.dividend_payout_ratio_ttm)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Margins & Returns */}
        <div className="flex-1 min-w-0">
          <div className="text-[9px] text-white/60 uppercase tracking-widest mb-1">Margins & Returns</div>
          <table className="w-full border-collapse">
            <tbody>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Gross Margin (TTM)</td>
                <td className="py-1 text-right text-terminal-amber font-bold text-[10px]">{formatPct(data.gross_margin_ttm)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Op Margin (TTM)</td>
                <td className="py-1 text-right text-terminal-amber font-bold text-[10px]">{formatPct(data.operating_margin_ttm)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Net Margin (TTM)</td>
                <td className="py-1 text-right text-terminal-amber font-bold text-[10px]">{formatPct(data.net_margin_ttm)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">ROCE / ROIC (FQ)</td>
                <td className="py-1 text-right text-terminal-green font-bold text-[10px]">{formatPct(data.return_on_invested_capital_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">ROE (FQ)</td>
                <td className="py-1 text-right text-terminal-green font-bold text-[10px]">{formatPct(data.return_on_equity_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">ROA (FQ)</td>
                <td className="py-1 text-right text-terminal-green font-bold text-[10px]">{formatPct(data.return_on_assets_fq)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Income & Cash Flow */}
        <div className="flex-1 min-w-0">
          <div className="text-[9px] text-white/60 uppercase tracking-widest mb-1">Income & Cash Flow (FQ)</div>
          <table className="w-full border-collapse">
            <tbody>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Total Revenue</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatCr(data.total_revenue_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">EBITDA</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatCr(data.ebitda_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Net Income</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatCr(data.net_income_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Operating CF</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatCr(data.cash_f_operating_activities_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Free Cash Flow</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatCr(data.free_cash_flow_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">CapEx</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatCr(data.capital_expenditures_fq)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Balance Sheet */}
        <div className="flex-1 min-w-0">
          <div className="text-[9px] text-white/60 uppercase tracking-widest mb-1">Balance Sheet & Debt (FQ)</div>
          <table className="w-full border-collapse">
            <tbody>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Total Assets</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatCr(data.total_assets_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Total Liabilities</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatCr(data.total_liabilities_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Total Equity</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatCr(data.total_equity_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Total Debt</td>
                <td className="py-1 text-right text-terminal-red font-bold text-[10px]">{formatCr(data.total_debt_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Cash & Equiv</td>
                <td className="py-1 text-right text-terminal-green font-bold text-[10px]">{formatCr(data.cash_n_equivalents_fq)}</td>
              </tr>
              <tr className="border-b border-terminal-gray/20">
                <td className="py-1 text-white/60 text-[10px]">Debt to Equity</td>
                <td className="py-1 text-right text-white font-bold text-[10px]">{formatNum(data.debt_to_equity_fq)}</td>
              </tr>
            </tbody>
          </table>
        </div>

      </div>
    </div>
  );
}
