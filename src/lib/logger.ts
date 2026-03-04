// Simple structured logger with timestamps and levels
// Usage: logger.info('Message', { key: value })

export type LogLevel = 'info' | 'warn' | 'error' | 'debug';

export interface LogContext {
  [key: string]: unknown;
}

class Logger {
  private formatTimestamp(): string {
    return new Date().toISOString();
  }

  private formatContext(context?: LogContext): string {
    if (!context || Object.keys(context).length === 0) {
      return '';
    }
    return ' ' + JSON.stringify(context);
  }

  info(message: string, context?: LogContext): void {
    console.log(`[${this.formatTimestamp()}] INFO: ${message}${this.formatContext(context)}`);
  }

  warn(message: string, context?: LogContext): void {
    console.warn(`[${this.formatTimestamp()}] WARN: ${message}${this.formatContext(context)}`);
  }

  error(message: string, context?: LogContext): void {
    console.error(`[${this.formatTimestamp()}] ERROR: ${message}${this.formatContext(context)}`);
  }

  debug(message: string, context?: LogContext): void {
    if (process.env.DEBUG) {
      console.debug(`[${this.formatTimestamp()}] DEBUG: ${message}${this.formatContext(context)}`);
    }
  }
}

export const logger = new Logger();
