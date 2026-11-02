'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useAtomValue, useSetAtom } from 'jotai';
import { useQuery } from '@tanstack/react-query';
import {
  activeExchangeAtom,
  activeSymbolAtom,
  aiChatModelAtom,
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
import { useWorkflowCatchUp } from '@/hooks/useWorkflowCatchUp';
import {
  useRunWorkflowNow,
  useDeleteWorkflow,
  useUpdateWorkflow,
  useWorkflowSummary,
  useWorkflowList,
} from '@/hooks/useAiWorkflows';
import {
  useMarkPromptUsed,
  useUpdatePrompt,
  useDeletePrompt,
  useCreatePrompt,
  useCustomPrompts,
} from '@/hooks/useAiCustomPrompts';
import type {
  Workflow,
  WorkflowCardPayload,
  PromptCardPayload,
  WorkflowUpdateInput,
  PromptUpdateInput,
  CustomPrompt,
  WorkflowRun,
} from '@/types/aiWorkflowTypes';
import type { StarterPrompt } from '@/types/aiWidgetTypes';
import { MessageBubble } from '@/components/widgets/AiChatMessages';
import { SessionSidebar } from '@/components/widgets/AiSessionSidebar';
import { AiModelDropdown } from '@/components/widgets/AiModelDropdown';
import { EmptyChatState, PersonaStrip } from '@/components/widgets/AiChatStarterViews';
import { AiInputBar } from '@/components/widgets/AiInputBar';
import { AiToolbar } from '@/components/widgets/AiToolbar';
import { AiWorkflowDrawer } from '@/components/widgets/AiWorkflowDrawer';
import { AiWorkflowModal } from '@/components/widgets/AiWorkflowModal';

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
  const rememberedModel = useAtomValue(aiChatModelAtom);
  const setRememberedModel = useSetAtom(aiChatModelAtom);

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
    launchPrompt,
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

  // Restore the last model the user picked. Runs once the catalog is known, so a
  // retired model id falls back to the catalog default instead of sticking.
  useEffect(() => {
    if (!rememberedModel) return;
    if (!availableModels.some((m) => m.id === rememberedModel)) return;
    if (model === rememberedModel) return;
    if (messages.length > 0 || isStreaming) return;
    patchSession(activeKey, { model: rememberedModel });
  }, [rememberedModel, availableModels, model, messages.length, isStreaming, activeKey, patchSession]);

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

  const runWorkflowNow = useRunWorkflowNow();
  const deleteWorkflow = useDeleteWorkflow();
  const updateWorkflow = useUpdateWorkflow();

  useWorkflowCatchUp();

  const createPrompt = useCreatePrompt();
  const markPromptUsed = useMarkPromptUsed();
  const updatePrompt = useUpdatePrompt();
  const deletePrompt = useDeletePrompt();

  const [promptPage, setPromptPage] = useState(0);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPromptPage(0);
  }, [sessionMode]);

  const { data: promptsData, isLoading: promptsLoading } = useCustomPrompts({
    mode: sessionMode,
    limit: 4,
    offset: promptPage * 4,
  });
  const userPrompts = promptsData?.items ?? [];
  const promptsTotal = promptsData?.total ?? 0;
  const promptsHasMore = promptsData?.has_more ?? false;

  const { data: workflowSummary } = useWorkflowSummary();
  const { data: workflowsData, isLoading: workflowsLoading } = useWorkflowList();

  const [workflowsOpen, setWorkflowsOpen] = useState(false);
  const [workflowModal, setWorkflowModal] = useState<{
    open: boolean;
    workflow: Workflow | null;
  }>({ open: false, workflow: null });

  const [activeRunBanner, setActiveRunBanner] = useState<{
    name: string;
    trigger: string;
    scheduledFor: string;
    note?: string;
  } | null>(null);

  const handleOpenRun = useCallback(
    (run: WorkflowRun) => {
      setWorkflowsOpen(false);
      setActiveRunBanner({
        name: run.name_snapshot || 'Workflow',
        trigger: run.trigger,
        scheduledFor: run.scheduled_for,
        note: run.session_id ? undefined : 'No transcript yet',
      });
      if (run.session_id) {
        void loadSession(run.session_id);
      }
    },
    [loadSession],
  );

  const handleCreatePromptWithAi = useCallback(
    (description: string) => {
      void sendMessage(
        `Create a reusable launch prompt card for me. What I want: "${description}". Call create_custom_prompt with a short title (max 40 chars), a 2-4 word uppercase tag, a one-line description (max 90 chars), and a well-structured prompt with an objective, scope, steps, and output format.`,
      );
    },
    [sendMessage],
  );

  const handleDuplicateSystemPrompt = useCallback(
    (p: StarterPrompt) => {
      createPrompt.mutate({
        title: p.title,
        tag: p.tag,
        description: p.desc,
        prompt: p.prompt,
        mode: sessionMode,
      });
    },
    [createPrompt, sessionMode],
  );

  const handleEditPrompt = useCallback(
    (p: CustomPrompt) => {
      updatePrompt.mutate({
        id: p.id,
        data: {
          title: p.title,
          tag: p.tag,
          description: p.description,
          prompt: p.prompt,
        },
      });
    },
    [updatePrompt],
  );

  const handleDeletePrompt = useCallback(
    (p: CustomPrompt) => {
      deletePrompt.mutate(p.id);
    },
    [deletePrompt],
  );

  const handleAskCopilot = useCallback(
    (description: string) => {
      const metaPrompt = `Create a scheduled workflow from this request: "${description}".

Call create_workflow with:
- name: short title, max 60 characters
- prompt: a self-contained instruction. State the objective, the scope (symbols, watchlist, or market), the checks to run, and the output format. Under 1200 characters.
- schedule_type and time_of_day: infer the cadence. Times are IST. Use weekdays for market-hours requests.
- symbols: the tickers named or implied, uppercase, max 10. Leave empty when the request covers a watchlist or the whole market.

Then confirm what you created in one sentence.`;
      launchPrompt(metaPrompt);
      setWorkflowsOpen(false);
      setWorkflowModal({ open: false, workflow: null });
    },
    [launchPrompt],
  );

  const dismissMessageCard = useCallback(
    (type: 'workflow' | 'prompt', card: WorkflowCardPayload | PromptCardPayload) => {
      setSessionMap((prev) => {
        const next = new Map(prev);
        const state = next.get(activeKey);
        if (!state) return prev;
        next.set(activeKey, {
          ...state,
          messages: state.messages.map((m) => {
            if (type === 'workflow' && m.workflowCard) {
              const match =
                card.id !== undefined ? m.workflowCard.id === card.id : m.workflowCard === card;
              if (match) {
                return { ...m, workflowCard: { ...m.workflowCard, dismissed: true } };
              }
            }
            if (type === 'prompt' && m.promptCard) {
              const match =
                card.id !== undefined ? m.promptCard.id === card.id : m.promptCard === card;
              if (match) {
                return { ...m, promptCard: { ...m.promptCard, dismissed: true } };
              }
            }
            return m;
          }),
        });
        return next;
      });
    },
    [activeKey, setSessionMap],
  );

  const handleWorkflowCardAction = useCallback(
    (
      action: 'run' | 'open' | 'undo' | 'apply' | 'discard' | 'edit',
      card: WorkflowCardPayload,
    ) => {
      if (action === 'run') {
        if (card.id !== undefined) {
          runWorkflowNow.mutate(card.id);
        }
      } else if (action === 'undo') {
        if (card.id !== undefined) {
          deleteWorkflow.mutate(card.id);
        }
        dismissMessageCard('workflow', card);
      } else if (action === 'discard') {
        dismissMessageCard('workflow', card);
      } else if (action === 'apply') {
        if (card.id !== undefined) {
          updateWorkflow.mutate({
            id: card.id,
            data: (card.changes ?? { prompt: card.prompt }) as WorkflowUpdateInput,
          });
        }
        dismissMessageCard('workflow', card);
      } else if (action === 'edit') {
        if (card.id !== undefined) {
          updateWorkflow.mutate({
            id: card.id,
            data: { prompt: card.prompt },
          });
        }
        dismissMessageCard('workflow', card);
      } else if (action === 'open') {
        setWorkflowsOpen(true);
      }
    },
    [runWorkflowNow, deleteWorkflow, updateWorkflow, dismissMessageCard],
  );

  const handlePromptCardAction = useCallback(
    (
      action: 'launch' | 'edit' | 'undo' | 'apply' | 'discard',
      card: PromptCardPayload,
    ) => {
      if (action === 'launch') {
        if (card.prompt) {
          launchPrompt(card.prompt);
        }
        if (card.id !== undefined) {
          markPromptUsed.mutate(card.id);
        }
      } else if (action === 'edit') {
        if (card.id !== undefined) {
          updatePrompt.mutate({
            id: card.id,
            data: { prompt: card.prompt },
          });
        }
        dismissMessageCard('prompt', card);
      } else if (action === 'apply') {
        if (card.id !== undefined) {
          updatePrompt.mutate({
            id: card.id,
            data: (card.changes ?? { prompt: card.prompt }) as PromptUpdateInput,
          });
        }
        dismissMessageCard('prompt', card);
      } else if (action === 'discard') {
        dismissMessageCard('prompt', card);
      } else if (action === 'undo') {
        if (card.id !== undefined) {
          deletePrompt.mutate(card.id);
        }
        dismissMessageCard('prompt', card);
      }
    },
    [launchPrompt, markPromptUsed, updatePrompt, deletePrompt, dismissMessageCard],
  );

  useEffect(() => {
    if (messages.length === 0) {
      const list = messagesEndRef.current?.parentElement;
      if (list) list.scrollTop = 0;
      return;
    }
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
        <div
          className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          data-testid="ai-disclaimer"
        >
          <div className="border border-terminal-amber/50 bg-[#09090b] p-4 text-center text-terminal-amber animate-pulse max-w-sm shadow-2xl rounded">
            <div className="font-bold mb-2 uppercase text-sm">⚠️ Disclaimer</div>
            <div className="text-[10px] leading-relaxed text-zinc-300">
              AI can make mistakes and the user takes all responsibility for any actions taken using the AI&apos;s advice/recommendations.
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
              setActiveRunBanner(null);
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
          workflowsOpen={workflowsOpen}
          onToggleWorkflows={() => setWorkflowsOpen((o) => !o)}
          armedWorkflows={workflowSummary?.armed ?? 0}
          unreadRuns={workflowSummary?.unread ?? 0}
          nextRunAt={workflowSummary?.next_run_at ?? null}
          model={model}
          defaultModel={defaultModel}
          onModelChange={(newModel) => {
            setRememberedModel(newModel);
            patchSession(activeKey, { model: newModel });
          }}
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
          onNewChat={() => {
            setActiveRunBanner(null);
            startNewChat(sessionMode);
          }}
        />

        {/* Workflow Run Banner */}
        {activeRunBanner && (
          <div className="px-3 py-1.5 bg-[#12100a] border-b border-terminal-amber/30 flex items-center gap-2 text-[10px] font-mono shrink-0 select-text">
            <span className="text-terminal-amber">⏱</span>
            <span className="text-zinc-200 font-bold truncate">{activeRunBanner.name}</span>
            <span className="text-zinc-500 uppercase">{activeRunBanner.trigger}</span>
            {activeRunBanner.note && (
              <span className="text-zinc-500 lowercase">({activeRunBanner.note})</span>
            )}
            <button
              type="button"
              onClick={() => setActiveRunBanner(null)}
              className="ml-auto text-zinc-400 hover:text-white"
              title="Close banner"
            >
              ✕
            </button>
          </div>
        )}

        {/* Scrollable Message List / Empty State */}
        <div className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-3 min-h-0 custom-scroll select-text">
          {messages.length === 0 ? (
            <EmptyChatState
              sessionMode={sessionMode}
              symbol={symbol}
              exchange={exchange}
              systemPrompts={starterPrompts}
              isStreaming={isStreaming}
              onLaunchPrompt={(prompt) => void sendMessage(prompt)}
              userPrompts={userPrompts}
              promptsLoading={promptsLoading}
              promptsTotal={promptsTotal}
              promptsPage={promptPage}
              promptsHasMore={promptsHasMore}
              onPageChange={setPromptPage}
              onCreatePrompt={handleCreatePromptWithAi}
              onEditPrompt={handleEditPrompt}
              onDeletePrompt={handleDeletePrompt}
              onDuplicateSystemPrompt={handleDuplicateSystemPrompt}
              armedWorkflows={workflowSummary?.armed}
              nextRunAt={workflowSummary?.next_run_at}
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
                  onWorkflowCardAction={handleWorkflowCardAction}
                  onPromptCardAction={handlePromptCardAction}
                />
              );
            })
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Persona Bento Strip */}
        <div data-widget-tour="ai-personas">
          <PersonaStrip
            activePersona={activePersona}
            onSelectPersona={setActivePersona}
          />
        </div>

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
          readOnly={Boolean(activeRunBanner)}
          onContinue={() => {
            setActiveRunBanner(null);
            startNewChat('research');
          }}
        />
      </div>

      {/* Collapsible Workflow Drawer */}
      <AiWorkflowDrawer
        open={workflowsOpen}
        onClose={() => setWorkflowsOpen(false)}
        workflows={workflowsData?.items ?? []}
        runs={[]}
        loading={workflowsLoading}
        runsLoading={false}
        onOpenRun={handleOpenRun}
        onCreateWorkflow={() => setWorkflowModal({ open: true, workflow: null })}
        onEditWorkflow={(w) => setWorkflowModal({ open: true, workflow: w })}
      />

      <AiWorkflowModal
        open={workflowModal.open}
        workflow={workflowModal.workflow}
        models={availableModels}
        onClose={() => setWorkflowModal({ open: false, workflow: null })}
        onAskCopilot={handleAskCopilot}
        onSaved={() => setWorkflowModal({ open: false, workflow: null })}
      />
    </div>
  );
}
