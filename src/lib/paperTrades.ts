export interface PaperTradeLeg {
  id: number;
  paper_trade_id: number;
  action: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaperTrade {
  id: number;
  symbol: string;
  status: 'OPEN' | 'CLOSED';
  created_at: string;
  updated_at: string;
  total_buy_quantity: number;
  total_sold_quantity: number;
  remaining_quantity: number;
  average_buy_price: number;
  average_sell_price?: number | null;
  realized_pnl: number;
  legs: PaperTradeLeg[];
  company_name?: string | null;
  pe?: number | null;
  technical_state: 'VOLATILE' | 'BUY' | 'SELL' | 'HOLD';
  last_close?: number | null;
}

export interface CreatePaperTradePayload {
  symbol: string;
  quantity: number;
  price: number;
  notes?: string;
}

export interface AddPaperTradeLegPayload {
  action: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  notes?: string;
}

export interface UpdatePaperTradeLegPayload {
  action?: 'BUY' | 'SELL';
  quantity?: number;
  price?: number;
  notes?: string;
}

export async function fetchPaperTrades(): Promise<PaperTrade[]> {
  const res = await fetch('/api/py/paper-trades');
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string; error?: string };
    throw new Error(data.detail || data.error || 'Failed to fetch paper trades');
  }
  return res.json();
}

export async function createPaperTrade(payload: CreatePaperTradePayload): Promise<PaperTrade> {
  const res = await fetch('/api/py/paper-trades', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string; error?: string };
    throw new Error(data.detail || data.error || 'Failed to create paper trade');
  }
  return res.json();
}

export async function addPaperTradeLeg(
  tradeId: number,
  payload: AddPaperTradeLegPayload,
): Promise<PaperTrade> {
  const res = await fetch(`/api/py/paper-trades/${tradeId}/legs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string; error?: string };
    throw new Error(data.detail || data.error || 'Failed to add trade leg');
  }
  return res.json();
}

export async function updatePaperTradeLeg(
  legId: number,
  payload: UpdatePaperTradeLegPayload,
): Promise<PaperTrade> {
  const res = await fetch(`/api/py/paper-trades/legs/${legId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string; error?: string };
    throw new Error(data.detail || data.error || 'Failed to update trade leg');
  }
  return res.json();
}

export async function deletePaperTradeLeg(legId: number): Promise<PaperTrade | { detail: string }> {
  const res = await fetch(`/api/py/paper-trades/legs/${legId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string; error?: string };
    throw new Error(data.detail || data.error || 'Failed to delete trade leg');
  }
  return res.json();
}

export async function deletePaperTrade(tradeId: number): Promise<void> {
  const res = await fetch(`/api/py/paper-trades/${tradeId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string; error?: string };
    throw new Error(data.detail || data.error || 'Failed to delete paper trade');
  }
}
