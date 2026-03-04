'use client';

import React, { Component, ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return { hasError: true, message };
  }

  override componentDidCatch(error: unknown, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  override render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center h-full text-xs font-mono text-terminal-red gap-2 p-4">
          <span className="font-bold">WIDGET ERROR</span>
          <span className="text-terminal-amber opacity-70 text-center break-all">{this.state.message}</span>
          <button
            className="mt-2 border border-terminal-amber text-terminal-amber px-3 py-1 hover:bg-terminal-amber hover:text-black transition-colors"
            onClick={() => this.setState({ hasError: false, message: '' })}
          >
            RETRY
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
