/**
 * Shared types and pure utility functions for AiWidget and AI hooks.
 */

export type AiMode = 'research' | 'script';

export interface ScriptCard {
  action: 'created' | 'revised';
  script_id: number;
  name: string;
  rev_no: number;
  accepted?: boolean;
  dismissed?: boolean;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: string[];
  isError?: boolean;
  card?: ScriptCard;
  attachments?: number[];
}

export interface AttachedDocument {
  id: number;
  filename: string;
  file_type: 'pdf' | 'csv';
  mime_type: string;
  file_size: number;
  row_count: number | null;
  page_count: number | null;
  needs_ocr: boolean;
  is_inlineable: boolean;
  summary?: Record<string, unknown>;
  attached_session_ids?: number[];
}

export interface ModelOption {
  id: string;
  label: string;
  is_free?: boolean;
}

export interface SessionSummary {
  id: number;
  title: string;
  model: string;
  symbol: string;
  exchange: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface SessionDetail {
  id: number;
  title: string;
  model: string;
  symbol: string;
  exchange: string;
  messages: Array<{
    id: number;
    role: string;
    content: string;
    tool_calls: string[] | null;
    attachments: number[] | null;
    created_at: string;
  }>;
  documents: AttachedDocument[];
}

export type StreamEvent =
  | { type: 'session_id'; id: number }
  | { type: 'token'; text: string }
  | { type: 'tool_call'; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; name: string; preview: string }
  | { type: 'script_card'; action: 'created' | 'revised'; script_id: number; name: string; rev_no: number }
  | { type: 'error'; message: string }
  | { type: 'done' };

export interface SessionState {
  messages: ChatMessage[];
  isStreaming: boolean;
  toolsDone: boolean;
  input: string;
  model: string;
  mode: AiMode;
  documents: AttachedDocument[];
  abortController: AbortController | null;
}

export function emptySessionState(defaultModel = '', mode: AiMode = 'research'): SessionState {
  return {
    messages: [],
    isStreaming: false,
    toolsDone: false,
    input: '',
    model: defaultModel,
    mode,
    documents: [],
    abortController: null,
  };
}

export const NEW_CHAT_KEY = null;

export const SUPPORTED_DOCUMENT_EXTENSIONS = ['.pdf', '.csv', '.tsv'];
export const MAX_ATTACHMENTS_PER_TURN = 5;

export function isSupportedDocument(file: File): boolean {
  const name = file.name.toLowerCase();
  return SUPPORTED_DOCUMENT_EXTENSIONS.some((extension) => name.endsWith(extension));
}

export function filterSupportedDocuments(files: ArrayLike<File>): File[] {
  return Array.from(files).filter(isSupportedDocument);
}

export function addAttachedDocument(
  existing: AttachedDocument[],
  document: AttachedDocument,
): AttachedDocument[] {
  if (existing.some((item) => item.id === document.id)) return existing;
  if (existing.length >= MAX_ATTACHMENTS_PER_TURN) return existing;
  return [...existing, document];
}

export function removeAttachedDocument(
  existing: AttachedDocument[],
  documentId: number,
): AttachedDocument[] {
  return existing.filter((item) => item.id !== documentId);
}

export async function detachSessionDocument(
  sessionId: number | null,
  documentId: number,
  fetchFn: typeof fetch = fetch,
): Promise<boolean> {
  if (sessionId === null || sessionId === undefined) {
    return true;
  }
  try {
    const res = await fetchFn(`/api/py/ai/documents/${documentId}/sessions/${sessionId}`, {
      method: 'DELETE',
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function sanitizeAiErrorMessage(message: string): string {
  const t = message.trim();
  if (/\{\s*"error"/.test(t)) {
    return 'The AI provider returned an unreadable error — please retry, or check the backend log for details.';
  }
  return message;
}

export function modeTrackClass(sessionMode: AiMode): string {
  return sessionMode === 'script'
    ? 'bg-emerald-400/15 border-emerald-400/50'
    : 'bg-terminal-amber/15 border-terminal-amber/40';
}

export function modeKnobClass(sessionMode: AiMode): string {
  return sessionMode === 'script'
    ? 'left-[calc(50%+1px)] bg-emerald-400 text-black font-bold'
    : 'left-[2px] bg-terminal-amber text-black font-bold';
}

export function shortModelLabel(label: string): string {
  return label.replace(/^\[[^\]]+\]\s*/, '');
}

export const PERSONAS = [
  { id: 'value',    label: '◈ Value Analyst',       description: 'Graham/Buffett intrinsic value & margin of safety lens' },
  { id: 'earnings', label: '📊 Earnings Forensics',  description: 'QoQ/YoY revenue, operating margin & cash conversion forensics' },
  { id: 'fno',      label: '⚡ F&O Derivatives',     description: 'Open interest buildup, PCR, implied volatility & option strategies' },
  { id: 'macro',    label: '🌐 Sector & Macro',      description: 'Sector rotation, FII/DII flows & macro policy impact' },
] as const;

export type PersonaId = (typeof PERSONAS)[number]['id'];

export interface StarterPrompt {
  tag: string;
  title: string;
  desc: string;
  prompt: string;
}

export function getResearchStarterPrompts(symbol: string, exchange: string): StarterPrompt[] {
  const sym = symbol ? symbol.toUpperCase() : 'NIFTY';
  const ex = exchange ? exchange.toUpperCase() : 'NSE';
  return [
    {
      tag: 'EQUITY VALUATION & FUNDAMENTALS',
      title: `Evaluate ${sym}`,
      desc: 'Multi-model intrinsic valuation, debt & margin forensics, ROCE/ROE trends, and DCF fair value.',
      prompt: `Perform a comprehensive fundamental and valuation analysis for ${sym}.${ex}. Evaluate: 1) P/E and EV/EBITDA multiples vs sector peers, 2) ROCE and ROE sustainability, 3) Debt-to-equity and interest coverage safety, 4) Operating margin and cash flow trends, and 5) Peter Lynch and DCF intrinsic fair value estimates. Provide clear actionable risk factors.`,
    },
    {
      tag: 'MACRO & MARKET PULSE',
      title: 'Indian Market Rundown',
      desc: 'NIFTY 50 & SENSEX levels, market breadth, sector leadership, FII/DII net flows, and VIX sentiment.',
      prompt: 'Provide a complete Indian market rundown today: 1) Benchmark indices (NIFTY 50, SENSEX, NIFTY BANK) price action and key support/resistance levels, 2) NSE market breadth (advances vs declines), 3) Top outperforming and lagging sectors, 4) FII and DII net cash market flows, and 5) India VIX regime and overall volatility outlook.',
    },
    {
      tag: 'GLOBAL SPILLOVER',
      title: 'Global News & Macro Context',
      desc: 'US & Asian markets, Treasury yields, Brent crude, DXY dollar index, and domestic sector implications.',
      prompt: 'Synthesize current global macro and geopolitical developments: 1) US and Asian market cues, 2) US 10-year Treasury yields and Federal Reserve interest rate expectations, 3) Brent Crude and commodity price trends, and 4) DXY US Dollar index movement. Detail specific positive and negative spillovers onto key Indian sectors (IT, Pharma, Auto, Energy).',
    },
    {
      tag: 'SCREENER & DISCOVERY',
      title: 'Find Next Investment Idea',
      desc: 'High-conviction asymmetric setups across NSE with high ROCE (>20%), low debt, rising FCF, and technical momentum.',
      prompt: 'Identify 3-4 high-conviction asymmetric investment candidates across the NSE universe. Screen for companies with: 1) High capital efficiency (ROCE > 20%, ROE > 18%), 2) Prudent leverage (Debt/Equity < 0.5), 3) Consistent Free Cash Flow generation with expanding operating margins, and 4) Technical momentum or consolidation breakout. Provide the thesis, key catalysts, and risk parameters for each candidate.',
    },
  ];
}

export function getScriptStarterPrompts(): StarterPrompt[] {
  return [
    {
      tag: 'OVERLAY SCRIPT',
      title: 'Σ Trend Ribbon (EMA 9/21/55)',
      desc: 'Multi-EMA institutional trend ribbon with dynamic bullish/bearish cloud fill and crossover signals.',
      prompt: 'Create an EMA 9, 21, and 55 trend ribbon indicator with dynamic cloud color fill and crossover signals.',
    },
    {
      tag: 'MEAN REVERSION',
      title: 'Σ Anchored VWAP + σ Bands',
      desc: 'Intraday anchored VWAP with upper and lower volatility exhaustion bands.',
      prompt: 'Build a VWAP indicator with +2 and -2 standard deviation bands for intraday mean reversion.',
    },
    {
      tag: 'MOMENTUM OSCILLATOR',
      title: 'Σ RSI Regime & Divergence',
      desc: 'RSI 14 with 70/30 overbought/oversold regime shading and price momentum divergence markers.',
      prompt: 'Write an RSI 14 script with 70/30 horizontal bands, regime coloring, and momentum divergence markers.',
    },
    {
      tag: 'VOLATILITY EXIT',
      title: 'Σ ATR Trailing Stop Line',
      desc: 'Dynamic chandelier exit stop line using 14-period Average True Range for risk management.',
      prompt: 'Create an ATR 14 trailing stop overlay script for systematic trend following and stop loss management.',
    },
  ];
}
