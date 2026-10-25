'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  NOTIF_CONFIG_KEYS,
  DEFAULT_NOTIF_CONFIG,
  type NotifConfigKey,
  type NotifConfigState,
} from './types';

export function useSettingsConfig({
  isOpen,
  isAuthenticated,
}: {
  isOpen: boolean;
  isAuthenticated: boolean;
}) {
  const qc = useQueryClient();
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [notifConfig, setNotifConfig] = useState<NotifConfigState>(DEFAULT_NOTIF_CONFIG);
  const [appVersion, setAppVersion] = useState<string>('');
  const [openAlgoUrlInput, setOpenAlgoUrlInput] = useState('');
  const [openAlgoApiKeyInput, setOpenAlgoApiKeyInput] = useState('');
  const [openAlgoKeyConfigured, setOpenAlgoKeyConfigured] = useState(false);
  const [aiHunterModel, setAiHunterModel] = useState('');
  const [aiVerifierModel, setAiVerifierModel] = useState('');
  const [systemConfigSaveStatus, setSystemConfigSaveStatus] = useState<string | null>(null);
  const [aiAuthStatus, setAiAuthStatus] = useState<{ provider: string; is_configured: boolean } | null>(null);

  const configRequestGenerationRef = useRef(0);

  const fetchSystemConfig = useCallback(async () => {
    if (!isOpen || !isAuthenticated) return;
    const requestGeneration = ++configRequestGenerationRef.current;
    setConfigLoading(true);
    setConfigError(null);
    try {
      const res = await fetch('/api/py/system-config');
      if (!res.ok) {
        throw new Error(`Failed to load system configuration (HTTP ${res.status})`);
      }
      const data = (await res.json()) as Record<string, unknown>;
      if (requestGeneration !== configRequestGenerationRef.current) return;
      setNotifConfig((current) => ({
        ...current,
        ...Object.fromEntries(
          NOTIF_CONFIG_KEYS.map((key) => [
            key,
            data[key] !== undefined ? String(data[key]) : current[key],
          ]),
        ),
      }));
      if (typeof data['app.version'] === 'string') {
        setAppVersion((prev) => prev || (data['app.version'] as string));
      }
      if (typeof data['openalgo.url'] === 'string') {
        setOpenAlgoUrlInput(data['openalgo.url']);
      }
      setOpenAlgoKeyConfigured(Boolean(data['openalgo.api_key_configured']));
      if (typeof data['ai.hunter_model'] === 'string') setAiHunterModel(data['ai.hunter_model']);
      if (typeof data['ai.verifier_model'] === 'string') setAiVerifierModel(data['ai.verifier_model']);
      setConfigError(null);
    } catch (err) {
      if (requestGeneration !== configRequestGenerationRef.current) return;
      const msg = err instanceof Error ? err.message : 'Failed to load system configuration';
      setConfigError(msg);
    } finally {
      if (requestGeneration === configRequestGenerationRef.current) {
        setConfigLoading(false);
      }
    }
  }, [isOpen, isAuthenticated]);

  useEffect(() => {
    if (isOpen && isAuthenticated) {
      void fetchSystemConfig();
    } else {
      configRequestGenerationRef.current++;
      setConfigLoading(false);
    }
    return () => {
      configRequestGenerationRef.current++;
    };
  }, [isOpen, isAuthenticated, fetchSystemConfig]);

  const systemConfigSaveTimerRef = useRef<Record<string, NodeJS.Timeout>>({});

  const scheduleSystemConfigSave = (key: string, value: string) => {
    const existingTimer = systemConfigSaveTimerRef.current[key];
    if (existingTimer) clearTimeout(existingTimer);
    systemConfigSaveTimerRef.current[key] = setTimeout(() => {
      fetch(`/api/py/system-config/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      })
        .then(async (res) => {
          if (!res.ok) {
            console.error(`Failed to save system config ${key}: HTTP ${res.status}`);
            setSystemConfigSaveStatus('Save failed');
            setTimeout(() => setSystemConfigSaveStatus(null), 3000);
            return;
          }
          setSystemConfigSaveStatus('Saved');
          setTimeout(() => setSystemConfigSaveStatus(null), 2000);
          if (key.startsWith('ai.')) {
            fetch('/api/py/ai/status').then(r => r.json()).then(d => setAiAuthStatus(d)).catch(console.error);
            qc.invalidateQueries({ queryKey: ['ai', 'routes'] });
            qc.invalidateQueries({ queryKey: ['ai', 'status'] });
            qc.invalidateQueries({ queryKey: ['ai', 'catalog'] });
            qc.invalidateQueries({ queryKey: ['ai-chat-models'] });
            qc.invalidateQueries({ queryKey: ['system-config'] });
          }
        })
        .catch((err) => {
          console.error(err);
          setSystemConfigSaveStatus('Save failed');
          setTimeout(() => setSystemConfigSaveStatus(null), 3000);
        });
    }, 500);
  };

  const configSaveTimerRef = useRef<Partial<Record<NotifConfigKey, NodeJS.Timeout>>>({});

  const scheduleNotifConfigSave = (key: NotifConfigKey, value: string) => {
    const existingTimer = configSaveTimerRef.current[key];
    if (existingTimer) clearTimeout(existingTimer);
    configSaveTimerRef.current[key] = setTimeout(() => {
      fetch(`/api/py/system-config/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: Number(value) }),
      })
        .then((res) => {
          if (!res.ok) {
            console.error(`Failed to save notif config ${key}: HTTP ${res.status}`);
          }
        })
        .catch(console.error);
    }, 300);
  };

  useEffect(() => {
    const timers = configSaveTimerRef.current;
    return () => {
      Object.values(timers).forEach((timer) => {
        if (timer) clearTimeout(timer);
      });
    };
  }, []);

  const handleNotifConfigChange = (key: NotifConfigKey, value: string) => {
    setNotifConfig((current) => ({ ...current, [key]: value }));
    if (!configLoading) {
      scheduleNotifConfigSave(key, value);
    }
  };

  return {
    configLoading,
    configError,
    notifConfig,
    appVersion,
    setAppVersion,
    openAlgoUrlInput,
    setOpenAlgoUrlInput,
    openAlgoApiKeyInput,
    setOpenAlgoApiKeyInput,
    openAlgoKeyConfigured,
    setOpenAlgoKeyConfigured,
    aiHunterModel,
    setAiHunterModel,
    aiVerifierModel,
    setAiVerifierModel,
    systemConfigSaveStatus,
    aiAuthStatus,
    setAiAuthStatus,
    fetchSystemConfig,
    scheduleSystemConfigSave,
    handleNotifConfigChange,
  };
}
