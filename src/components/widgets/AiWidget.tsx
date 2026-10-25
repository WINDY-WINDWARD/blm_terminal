'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useAtomValue, useSetAtom } from 'jotai';
import { useQuery } from '@tanstack/react-query';
import {
  activeExchangeAtom,
  activeSymbolAtom,
  showSettingsModalAtom,
  settingsModalTabAtom,
} from '@/store/terminalStore';

import {
  formatBytes,
  getResearchStarterPrompts,
  getScriptStarterPrompts,
  modeKnobClass,
  modeTrackClass,
  sanitizeAiErrorMessage,
  shortModelLabel,
  MAX_ATTACHMENTS_PER_TURN,
  isSupportedDocument,
  filterSupportedDocuments,
  addAttachedDocument,
  removeAttachedDocument,
  detachSessionDocument,
  SUPPORTED_DOCUMENT_EXTENSIONS,
  type AiMode,
  type AttachedDocument,
  type ChatMessage,
  type ScriptCard,
  type SessionState,
  type SessionSummary,
} from '@/types/aiWidgetTypes';

import { useAiSessionPersistence } from '@/hooks/useAiSessionPersistence';
import { useAiChatSession } from '@/hooks/useAiChatSession';
import { useAiDocuments } from '@/hooks/useAiDocuments';
import { useAiModels } from '@/hooks/useAiModels';
import { useScriptHandoff } from '@/hooks/useScriptHandoff';
import { MessageBubble } from '@/components/widgets/AiChatMessages';
import { SessionSidebar } from '@/components/widgets/AiSessionSidebar';
import { AiModelDropdown } from '@/components/widgets/AiModelDropdown';
import { EmptyChatState, PersonaStrip } from '@/components/widgets/AiChatStarterViews';
import { AiInputBar } from '@/components/widgets/AiInputBar';
import { AiToolbar } from '@/components/widgets/AiToolbar';

// Re-exports to preserve exact contract for existing tests and external consumers
export {
  sanitizeAiErrorMessage,
  modeTrackClass,
  modeKnobClass,
  shortModelLabel,
  SUPPORTED_DOCUMENT_EXTENSIONS,
  MAX_ATTACHMENTS_PER_TURN,
  isSupportedDocument,
  filterSupportedDocuments,
  addAttachedDocument,
  removeAttachedDocument,
  detachSessionDocument,
  formatBytes,
  AiModelDropdown,
};

export type { AttachedDocument, AiMode, ScriptCard, ChatMessage, SessionState };

export function AiWidget() {
  const setShowSettingsModal = useSetAtom(showSettingsModalAtom);
  const setSettingsModalTab = useSetAtom(settingsModalTabAtom);
  const symbol = useAtomValue(activeSymbolAtom);
  const exchange = useAtomValue(activeExchangeAtom);

  const [showDisclaimer, setShowDisclaimer] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => setShowDisclaimer(false), 4000);
    return () => clearTimeout(timer);
  }, []);

  const {
    catalogData,
    modelsLoading,
    modelsError,
    refetchModels,
    availableModels,
    defaultModel,
    aiAuthStatus,
  } = useAiModels();

  const {
    sessionMap,
    setSessionMap,
    activeKey,
    setActiveKey,
    hasSentRef,
    patchSession,
  } = useAiSessionPersistence(defaultModel);

  const { data: sessions = [], refetch: refetchSessions } = useQuery<SessionSummary[]>({
    queryKey: ['ai-chat-sessions'],
    queryFn: async () => {
      const res = await fetch('/api/py/ai/chat/sessions');
      if (!res.ok) return [];
      return res.json();
    },
    staleTime: 0,
    refetchOnMount: true,
  });

  const {
    currentSession,
    activePersona,
    setActivePersona,
    streamRouteLabel,
    streamElapsed,
    streamingKeys,
    sendMessage,
    handleStop,
    retryLastMessage,
    startNewChat,
    loadSession,
    deleteSession,
  } = useAiChatSession({
    sessionMap,
    setSessionMap,
    activeKey,
    setActiveKey,
    patchSession,
    defaultModel,
    availableModels,
    catalogData,
    symbol,
    exchange,
    hasSentRef,
    refetchSessions,
    inputRef,
  });

  const { messages, isStreaming, toolsDone, input, model, mode: sessionMode = 'research', documents } = currentSession;
  const sessionDocuments = documents ?? [];

  const {
    libraryDocuments,
    uploadJobs,
    dragActive,
    setDragActive,
    uploadFile,
    removeSessionDocument,
    attachLibraryDocument,
    deleteLibraryDocument,
    handleDocumentDrop,
  } = useAiDocuments({
    activeKey,
    sessionMap,
    setSessionMap,
    defaultModel,
  });

  const { acceptCard, discardCard } = useScriptHandoff({
    activeKey,
    setActiveKey,
    setSessionMap,
    patchSession,
    inputRef,
  });

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [activeKey]);

  const starterPrompts =
    sessionMode === 'script' ? getScriptStarterPrompts() : getResearchStarterPrompts(symbol, exchange);

  return (
    <div className="h-full w-full flex overflow-hidden font-mono text-xs bg-[#09090b] text-[#f4f4f5] relative select-none">
      {/* Disclaimer Modal */}
      {showDisclaimer && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="border border-terminal-amber/50 bg-[#09090b] p-4 text-center text-terminal-amber animate-pulse max-w-sm shadow-2xl rounded">
            <div className="font-bold mb-2 uppercase text-sm">⚠️ Disclaimer</div>
            <div className="text-[10px] leading-relaxed text-zinc-300">
              AI can make mistakes and the user takes all responsibility for any actions taken using the AI's advice/recommendations.
            </div>
          </div>
        </div>
      )}

      {/* Provider Configuration Banner */}
      {aiAuthStatus && !aiAuthStatus.is_configured && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="border border-rose-500/50 bg-[#09090b] p-6 text-center text-rose-400 shadow-2xl max-w-sm flex flex-col items-center gap-3 rounded">
            <div className="font-bold uppercase text-lg">⚠️ Configuration Required</div>
            <div className="text-xs text-zinc-300 leading-relaxed font-mono">
              The AI Provider ({aiAuthStatus.provider}) is not fully configured.
              Please complete the setup in <button type="button" onClick={() => { setSettingsModalTab('intelligence'); setShowSettingsModal(true); }} className="text-terminal-amber font-bold underline hover:text-white cursor-pointer">Settings</button>.
            </div>
            <div className="text-[10px] text-zinc-500 mt-2 font-mono">
              (This widget is locked until a valid provider is set)
            </div>
          </div>
        </div>
      )}

      {/* Collapsible Session Drawer */}
      {sidebarOpen && (
        <aside className="w-64 bg-[#0c0c0f] border-r border-[#27272a] flex flex-col shrink-0 z-20 transition-all">
          <SessionSidebar
            sessions={sessions}
            libraryDocuments={libraryDocuments}
            attachedDocumentIds={sessionDocuments.map((document) => document.id)}
            activeKey={activeKey}
            streamingKeys={streamingKeys}
            onSelectSession={(id) => {
              void loadSession(id);
              setSidebarOpen(false);
            }}
            onDeleteSession={(id) => void deleteSession(id)}
            onNewChat={() => {
              startNewChat();
              setSidebarOpen(false);
            }}
            onAttachDocument={attachLibraryDocument}
            onDeleteDocument={(id) => void deleteLibraryDocument(id)}
          />
        </aside>
      )}

      {/* Main Workspace */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0 bg-[#09090b]">
        {/* Unified Bento Command Toolbar */}
        <AiToolbar
          sidebarOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen((o) => !o)}
          sessionCount={sessions.length}
          model={model}
          defaultModel={defaultModel}
          onModelChange={(newModel) => patchSession(activeKey, { model: newModel })}
          isStreaming={isStreaming}
          availableModels={availableModels}
          catalogData={catalogData}
          modelsLoading={modelsLoading}
          modelsError={modelsError}
          onRetryModels={() => void refetchModels()}
          symbol={symbol}
          exchange={exchange}
          streamRouteLabel={streamRouteLabel}
          streamElapsed={streamElapsed}
          sessionMode={sessionMode}
          onToggleMode={() => patchSession(activeKey, { mode: sessionMode === 'script' ? 'research' : 'script' })}
          onNewChat={() => startNewChat(sessionMode)}
        />

        {/* Scrollable Message List / Empty State */}
        <div className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-3 min-h-0 custom-scroll">
          {messages.length === 0 ? (
            <EmptyChatState
              sessionMode={sessionMode}
              symbol={symbol}
              exchange={exchange}
              starterPrompts={starterPrompts}
              isStreaming={isStreaming}
              onLaunchPrompt={(prompt) => void sendMessage(prompt)}
            />
          ) : (
            messages.map((msg, i) => {
              const isLastAssistant = msg.role === 'assistant' && i === messages.length - 1;
              return (
                <MessageBubble
                  key={i}
                  msg={msg}
                  documents={documents}
                  isLastAssistant={isLastAssistant}
                  toolsDone={isLastAssistant ? toolsDone : undefined}
                  onRetry={isLastAssistant ? retryLastMessage : undefined}
                  onAcceptCard={acceptCard}
                  onDiscardCard={discardCard}
                />
              );
            })
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Persona Bento Strip */}
        <PersonaStrip
          activePersona={activePersona}
          onSelectPersona={setActivePersona}
        />

        {/* Elevated Bento Input Bar */}
        <AiInputBar
          input={input}
          onChangeInput={(val) => patchSession(activeKey, { input: val })}
          onSend={sendMessage}
          onStop={handleStop}
          isStreaming={isStreaming}
          sessionMode={sessionMode}
          symbol={symbol}
          exchange={exchange}
          sessionDocuments={sessionDocuments}
          uploadJobs={uploadJobs}
          dragActive={dragActive}
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDocumentDrop}
          onRemoveDocument={(id) => void removeSessionDocument(id)}
          onUploadFile={uploadFile}
          inputRef={inputRef}
        />
      </div>
    </div>
  );
}
