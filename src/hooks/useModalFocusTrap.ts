'use client';

import { useEffect, useRef } from 'react';

interface ModalStackEntry {
  id: string;
  onClose?: () => void;
  container: HTMLElement;
}

const modalStack: ModalStackEntry[] = [];
let isListenerAttached = false;

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter((el) => {
    if (el.hasAttribute('disabled')) return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;
    return true;
  });
}

function handleGlobalKeyDown(e: KeyboardEvent) {
  if (modalStack.length === 0) return;
  const top = modalStack[modalStack.length - 1];

  if (e.key === 'Escape') {
        if (top.onClose) {
      e.preventDefault();
      e.stopPropagation();
      top.onClose();
    }
    return;
  }

  if (e.key === 'Tab') {
    const focusables = getFocusableElements(top.container);
    if (focusables.length === 0) {
      e.preventDefault();
      top.container.focus();
      return;
    }

    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const current = document.activeElement;

    if (e.shiftKey) {
      if (current === first || !top.container.contains(current)) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (current === last || !top.container.contains(current)) {
        e.preventDefault();
        first.focus();
      }
    }
  }
}

function handleGlobalFocusIn(e: FocusEvent) {
  if (modalStack.length === 0) return;
  const top = modalStack[modalStack.length - 1];
  if (!top.container.contains(e.target as Node)) {
    // Focus escaped the topmost modal container; redirect into topmost modal
    const focusables = getFocusableElements(top.container);
    if (focusables.length > 0) {
      focusables[0].focus();
    } else {
      top.container.focus();
    }
  }
}

function attachGlobalListeners() {
  if (!isListenerAttached && typeof window !== 'undefined') {
    window.addEventListener('keydown', handleGlobalKeyDown, true);
    window.addEventListener('focusin', handleGlobalFocusIn, true);
    isListenerAttached = true;
  }
}

function detachGlobalListeners() {
  if (isListenerAttached && modalStack.length === 0 && typeof window !== 'undefined') {
    window.removeEventListener('keydown', handleGlobalKeyDown, true);
    window.removeEventListener('focusin', handleGlobalFocusIn, true);
    isListenerAttached = false;
  }
}

export interface UseModalFocusTrapOptions {
  id: string;
  isOpen: boolean;
  onClose?: () => void;
  containerRef: React.RefObject<HTMLElement | null>;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
  autoFocus?: boolean;
}

export function useModalFocusTrap({
  id,
  isOpen,
  onClose,
  containerRef,
  initialFocusRef,
  autoFocus = true,
}: UseModalFocusTrapOptions) {
  const previousActiveElementRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!isOpen) return;

    const container = containerRef.current;
    if (!container) return;

    // Store previously focused element to restore later
    previousActiveElementRef.current = document.activeElement as HTMLElement | null;

    // Push entry to top of modal stack
    const entry: ModalStackEntry = {
      id,
      container,
      onClose: () => onCloseRef.current?.(),
    };
    modalStack.push(entry);
    attachGlobalListeners();

    // Set initial focus
    if (autoFocus) {
      setTimeout(() => {
        if (!containerRef.current) return;
        if (initialFocusRef?.current) {
          initialFocusRef.current.focus();
        } else {
          const focusables = getFocusableElements(containerRef.current);
          if (focusables.length > 0) {
            focusables[0].focus();
          } else {
            containerRef.current.focus();
          }
        }
      }, 0);
    }

    return () => {
      // Remove from stack
      const idx = modalStack.findIndex((item) => item.id === id);
      if (idx !== -1) {
        modalStack.splice(idx, 1);
      }
      detachGlobalListeners();

      // Restore focus to previous element if valid
      const prev = previousActiveElementRef.current;
      if (prev && typeof prev.focus === 'function' && document.body.contains(prev)) {
        prev.focus();
      }
    };
  }, [id, isOpen, containerRef, initialFocusRef, autoFocus]);
}
