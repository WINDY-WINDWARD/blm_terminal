import { io, Socket } from 'socket.io-client';

class WebSocketService {
    private static instance: WebSocketService;
    public socket: Socket | null = null;
    private baseURL = process.env.NEXT_PUBLIC_OPENALGO_URL || 'http://localhost:5000';

    private constructor() { }

    public static getInstance(): WebSocketService {
        if (!WebSocketService.instance) {
            WebSocketService.instance = new WebSocketService();
        }
        return WebSocketService.instance;
    }

    public connect() {
        if (!this.socket) {
            this.socket = io(this.baseURL, {
                reconnectionAttempts: 5,
                reconnectionDelay: 1000,
                autoConnect: true,
            });

            this.socket.on('connect', () => {
                console.log('OpenAlgo WebSocket Connected');
            });

            this.socket.on('disconnect', () => {
                console.log('OpenAlgo WebSocket Disconnected');
            });
        }
    }

    public disconnect() {
        if (this.socket) {
            this.socket.disconnect();
            this.socket = null;
        }
    }

    public subscribe(symbol: string) {
        if (this.socket) {
            this.socket.emit('subscribe', { symbols: [symbol] });
        }
    }

    public unsubscribe(symbol: string) {
        if (this.socket) {
            this.socket.emit('unsubscribe', { symbols: [symbol] });
        }
    }
}

export const wsService = WebSocketService.getInstance();
