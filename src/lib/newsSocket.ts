import { withTicket } from './wsTicket';

export interface NewsArticle {
  url: string;
  source: string | null;
  title: string | null;
  text: string | null;
  publish_date: string | null;
  fetched_at: string | null;
  company_symbol: string | null;
  sentiment: string | null;
  sentiment_score: number | null;
  confidence: number | null;
  language: string | null;
  entities: Record<string, unknown> | null;
  threat_level: string | null;
  threat_category: string | null;
  source_credibility: string | null;
}

export interface NewsWsMessage {
  type: 'connected' | 'news' | 'subscribed' | 'recent_articles' | 'heartbeat' | 'pong';
  message?: string;
  article?: NewsArticle;
  sources?: string[];
  articles?: NewsArticle[];
}

type NewsHandler = (article: NewsArticle) => void;
type ConnectionHandler = (connected: boolean) => void;

class NewsWebSocketService {
  private static instance: NewsWebSocketService;
  private socket: WebSocket | null = null;
  private connected = false;
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 10;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  private newsListeners: Set<NewsHandler> = new Set();
  private connectionListeners: Set<ConnectionHandler> = new Set();
  private _recentArticles: NewsArticle[] = [];
  private subscribedSources: Set<string> = new Set();

  private wsUrl: string | null = null;
  private wsUrlFetchInitiated = false;

  private constructor() {}

  public static getInstance(): NewsWebSocketService {
    if (!NewsWebSocketService.instance) {
      NewsWebSocketService.instance = new NewsWebSocketService();
    }
    return NewsWebSocketService.instance;
  }

  public connect(): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      console.log('[newsSocket] Already connected');
      return;
    }
    if (this.socket && this.socket.readyState === WebSocket.CONNECTING) return;

    if (!this.wsUrl && !this.wsUrlFetchInitiated) {
      this.wsUrlFetchInitiated = true;
      this.fetchWsUrl().then((url) => {
        if (url) {
          this.wsUrl = url;
          this.openSocket();
        } else {
          console.warn('[newsSocket] Failed to fetch WS URL, retrying in 2s');
          setTimeout(() => {
            this.wsUrlFetchInitiated = false;
            this.connect();
          }, 2000);
        }
      });
      return;
    }

    if (!this.wsUrl) return; // still waiting for URL
    this.openSocket();
  }

  private async fetchWsUrl(): Promise<string | null> {
    const envUrl = process.env.NEXT_PUBLIC_NEWS_WS_URL;
    if (envUrl) {
      return envUrl;
    }
    return this.localhostFallback();
  }

  private localhostFallback(): string {
    const ws = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${ws}://${window.location.host}/ws/news`;
  }

  private async openSocket(): Promise<void> {
    if (!this.wsUrl) return;
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) return;

    console.log('[newsSocket] Connecting to', this.wsUrl);
    try {
      const url = await withTicket(this.wsUrl);
      this.socket = new WebSocket(url);

      this.socket.onopen = () => {
        console.log('[newsSocket] Connected');
        this.reconnectAttempts = 0;
        this.connected = true;
        this.notifyConnection(true);
        // Re-subscribe to any sources registered before connection
        if (this.subscribedSources.size > 0) {
          this.send({ action: 'subscribe', sources: [...this.subscribedSources] });
        }
      };

      this.socket.onmessage = (event: MessageEvent) => {
        this.handleMessage(event);
      };

      this.socket.onerror = (event) => {
        console.error('[newsSocket] Error:', event);
      };

      this.socket.onclose = () => {
        console.log('[newsSocket] Disconnected');
        this.connected = false;
        this.notifyConnection(false);
        this.scheduleReconnect();
      };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[newsSocket] Failed to open WebSocket:', msg);
    }
  }

  public disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.close();
      this.socket = null;
    }
    this.connected = false;
    this.wsUrlFetchInitiated = false;
    this.notifyConnection(false);
  }

  public subscribe(sources: string[]): void {
    this.subscribedSources = new Set(sources);
    if (this.connected) {
      this.send({ action: 'subscribe', sources });
    }
  }

  public getRecent(limit = 20): void {
    if (this.connected) {
      this.send({ action: 'get_recent', limit });
    }
  }

  public onNews(handler: NewsHandler): () => void {
    this.newsListeners.add(handler);
    return () => this.newsListeners.delete(handler);
  }

  public onConnectionChange(handler: ConnectionHandler): () => void {
    this.connectionListeners.add(handler);
    return () => this.connectionListeners.delete(handler);
  }

  public get isConnected(): boolean {
    return this.connected;
  }

  public get recentArticles(): NewsArticle[] {
    return this._recentArticles;
  }

  private send(payload: Record<string, unknown>): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
    }
  }

  private handleMessage(event: MessageEvent): void {
    let msg: NewsWsMessage;
    try {
      msg = JSON.parse(event.data as string) as NewsWsMessage;
    } catch {
      return;
    }

    switch (msg.type) {
      case 'connected':
        console.log('[newsSocket] Server:', msg.message);
        break;
      case 'news':
        if (msg.article) {
          this._recentArticles.unshift(msg.article);
          if (this._recentArticles.length > 100) {
            this._recentArticles.pop();
          }
          this.newsListeners.forEach((handler) => handler(msg.article!));
        }
        break;
      case 'recent_articles':
        if (msg.articles) {
          this._recentArticles = msg.articles;
        }
        break;
      case 'subscribed':
        if (msg.sources) {
          this.subscribedSources = new Set(msg.sources);
        }
        break;
      case 'heartbeat':
        break;
      case 'pong':
        break;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.warn('[newsSocket] Max reconnect attempts reached');
      return;
    }
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    this.reconnectAttempts++;
    console.log(`[newsSocket] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  private notifyConnection(connected: boolean): void {
    this.connectionListeners.forEach((handler) => handler(connected));
  }
}

export const newsSocketService = NewsWebSocketService.getInstance();