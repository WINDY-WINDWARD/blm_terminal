export class OpenAlgoClient {
    private static baseURL = process.env.NEXT_PUBLIC_OPENALGO_URL || 'http://localhost:5000';
    private static apiKey = process.env.NEXT_PUBLIC_OPENALGO_API_KEY || '';

    private static async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
        const url = `${this.baseURL}${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.apiKey}`,
            ...options.headers,
        };

        const response = await fetch(url, { ...options, headers });
        if (!response.ok) {
            throw new Error(`OpenAlgo API Error: ${response.statusText}`);
        }
        return response.json();
    }

    static async getPositions() {
        return this.request('/api/v1/positions');
    }

    static async getQuotes(symbols: string[]) {
        return this.request(`/api/v1/quotes?symbols=${symbols.join(',')}`);
    }

    static async placeOrder(payload: { symbol: string; side: 'BUY' | 'SELL'; quantity: number; type: 'MARKET' | 'LIMIT'; price?: number }) {
        return this.request('/api/v1/placeorder', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    }
}
