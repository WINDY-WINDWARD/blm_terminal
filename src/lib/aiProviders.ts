/**
 * Shared AI provider metadata — single source of truth for provider setup UX.
 *
 * Used by SettingsWidget and FirstLaunchModal so both surfaces show identical
 * provider lists, credential fields, and step-by-step setup instructions.
 */

export type AiProviderKind = 'free' | 'api-key' | 'oauth';

export interface AiProviderSetupLink {
  label: string;
  url: string;
}

export interface AiProviderMeta {
  /** Provider id stored in `ai.provider`. */
  id: string;
  /** Dropdown label. */
  label: string;
  kind: AiProviderKind;
  /** Credential input label (api-key kind only). */
  credentialLabel?: string;
  /** system_config slot for the credential (api-key kind only). */
  credentialDbKey?: string;
  placeholder?: string;
  hint?: string;
  /** e.g. 'Requires an active Claude Pro or Max subscription.' */
  requiresSubscription?: string;
  /** e.g. 'Requires the Claude Code CLI (one-time, only to mint the token).' */
  requiresApp?: string;
  /** Numbered setup instructions shown under the credential input. */
  steps: string[];
  links: AiProviderSetupLink[];
}

export const AI_PROVIDERS: AiProviderMeta[] = [
  {
    id: 'zen-paid',
    label: 'OpenCode Zen (Paid)',
    kind: 'api-key',
    credentialLabel: 'Zen (Paid) API Key',
    credentialDbKey: 'ai.zen_api_key',
    placeholder: 'Enter Zen API key',
    steps: [
      'Sign up at opencode.ai/auth and subscribe to a paid tier.',
      'Copy your API key from the OpenCode dashboard.',
      'Paste it above — it saves automatically.',
    ],
    links: [{ label: 'opencode.ai/auth', url: 'https://opencode.ai/auth' }],
  },
  {
    id: 'go',
    label: 'OpenCode Go',
    kind: 'api-key',
    credentialLabel: 'Go API Key',
    credentialDbKey: 'ai.go_api_key',
    placeholder: 'Enter Go API key',
    steps: [
      'Get an OpenCode Go API key from your OpenCode account.',
      'Paste it above — it saves automatically.',
    ],
    links: [{ label: 'opencode.ai/auth', url: 'https://opencode.ai/auth' }],
  },
  {
    id: 'gemini',
    label: 'Google Pro',
    kind: 'oauth',
    requiresSubscription: 'Uses your existing Google subscription via the Antigravity proxy.',
    steps: [
      'Click “Login to Gemini” below.',
      'Complete Google sign-in in the browser window.',
      'Return here — status flips to Connected automatically.',
    ],
    links: [],
  },
  {
    id: 'aistudio',
    label: 'Google AI Studio',
    kind: 'api-key',
    credentialLabel: 'AI Studio API Key',
    credentialDbKey: 'ai.aistudio_api_key',
    placeholder: 'Enter AI Studio API key (AIza-…)',
    hint: 'Get your free key at aistudio.google.com — see the Get Started guide there.',
    steps: [
      'Open aistudio.google.com and sign in with Google.',
      'Click “Get API key” and create a key (free tier available).',
      'Paste it above — it saves automatically.',
    ],
    links: [{ label: 'aistudio.google.com', url: 'https://aistudio.google.com' }],
  },
  {
    id: 'groq',
    label: 'Groq',
    kind: 'api-key',
    credentialLabel: 'Groq API Key',
    credentialDbKey: 'ai.groq_api_key',
    placeholder: 'Enter Groq API key (gsk-…)',
    hint: 'Get your key at console.groq.com — see the Quickstart docs there.',
    steps: [
      'Open console.groq.com and sign in.',
      'Go to API Keys and create a key (starts with gsk-…).',
      'Paste it above — it saves automatically.',
    ],
    links: [{ label: 'console.groq.com', url: 'https://console.groq.com' }],
  },
  {
    id: 'nvidia',
    label: 'NVIDIA NIM',
    kind: 'api-key',
    credentialLabel: 'NVIDIA API Key',
    credentialDbKey: 'ai.nvidia_api_key',
    placeholder: 'Enter NVIDIA API key (nvapi-…)',
    hint: 'Get your key at build.nvidia.com — see the NIM LLM API docs there.',
    steps: [
      'Open build.nvidia.com and sign in.',
      'Generate an API key (starts with nvapi-…).',
      'Paste it above — it saves automatically.',
    ],
    links: [{ label: 'build.nvidia.com', url: 'https://build.nvidia.com' }],
  },
  {
    id: 'anthropic',
    label: 'Anthropic (API key)',
    kind: 'api-key',
    credentialLabel: 'Anthropic API Key',
    credentialDbKey: 'ai.anthropic_api_key',
    placeholder: 'Enter Anthropic API key (sk-ant-…)',
    hint: 'Get your key at console.anthropic.com — usage-based billing applies.',
    requiresSubscription: 'Usage-based billing applies — enable billing on your Anthropic account.',
    steps: [
      'Open console.anthropic.com and sign in.',
      'Go to API keys and create a key (starts with sk-ant-…).',
      'Paste it above — it saves automatically.',
    ],
    links: [{ label: 'console.anthropic.com', url: 'https://console.anthropic.com' }],
  },
  {
    id: 'claude-code',
    label: 'Claude Code (subscription token)',
    kind: 'api-key',
    credentialLabel: 'Claude Code OAuth Token',
    credentialDbKey: 'ai.claude_code_token',
    placeholder: 'Paste token from `claude setup-token` (sk-ant-oat01-…)',
    hint: 'Run `claude setup-token` in the Claude Code CLI and paste the token — uses your Claude subscription, no API billing.',
    requiresSubscription: 'Requires an active Claude Pro or Max subscription.',
    requiresApp: 'Requires the Claude Code CLI installed (one-time — only to mint the token).',
    steps: [
      'Install the Claude Code CLI if needed: npm i -g @anthropic-ai/claude-code.',
      'Run `claude setup-token` and approve in the browser.',
      'Copy the printed token (starts with sk-ant-oat01-…) and paste it above.',
    ],
    links: [{ label: 'Claude Code auth docs', url: 'https://code.claude.com/docs/en/authentication' }],
  },
  {
    id: 'openai',
    label: 'OpenAI (API key)',
    kind: 'api-key',
    credentialLabel: 'OpenAI API Key',
    credentialDbKey: 'ai.openai_api_key',
    placeholder: 'Enter OpenAI API key (sk-…)',
    hint: 'Get your key at platform.openai.com — usage-based billing applies.',
    requiresSubscription: 'Usage-based billing applies — add billing on your OpenAI account.',
    steps: [
      'Open platform.openai.com and sign in.',
      'Go to API keys and create a key (starts with sk-…).',
      'Paste it above — it saves automatically.',
    ],
    links: [{ label: 'platform.openai.com', url: 'https://platform.openai.com/api-keys' }],
  },
  {
    id: 'openrouter',
    label: 'OpenRouter (API key)',
    kind: 'api-key',
    credentialLabel: 'OpenRouter API Key',
    credentialDbKey: 'ai.openrouter_api_key',
    placeholder: 'Enter OpenRouter API key (sk-or-…)',
    hint: 'Get your key at openrouter.ai — 300+ models, tool-capable ones are listed.',
    steps: [
      'Open openrouter.ai and sign in.',
      'Go to Keys and create a key (starts with sk-or-…).',
      'Paste it above — tool-capable models with 8k+ context are listed automatically.',
    ],
    links: [{ label: 'openrouter.ai', url: 'https://openrouter.ai/keys' }],
  },
  {
    id: 'deepseek',
    label: 'DeepSeek (API key)',
    kind: 'api-key',
    credentialLabel: 'DeepSeek API Key',
    credentialDbKey: 'ai.deepseek_api_key',
    placeholder: 'Enter DeepSeek API key (sk-…)',
    hint: 'Get your key at platform.deepseek.com.',
    steps: [
      'Open platform.deepseek.com and sign in.',
      'Go to API keys and create a key (starts with sk-…).',
      'Paste it above — it saves automatically.',
    ],
    links: [{ label: 'platform.deepseek.com', url: 'https://platform.deepseek.com/api_keys' }],
  },
  {
    id: 'xai',
    label: 'xAI Grok (API key)',
    kind: 'api-key',
    credentialLabel: 'xAI API Key',
    credentialDbKey: 'ai.xai_api_key',
    placeholder: 'Enter xAI API key (xai-…)',
    hint: 'Get your key at console.x.ai.',
    steps: [
      'Open console.x.ai and sign in.',
      'Go to API keys and create a key (starts with xai-…).',
      'Paste it above — it saves automatically.',
    ],
    links: [{ label: 'console.x.ai', url: 'https://console.x.ai' }],
  },
  {
    id: 'together',
    label: 'Together AI (API key)',
    kind: 'api-key',
    credentialLabel: 'Together AI API Key',
    credentialDbKey: 'ai.together_api_key',
    placeholder: 'Enter Together API key',
    hint: 'Get your key at api.together.ai.',
    steps: [
      'Open api.together.ai and sign in.',
      'Go to API keys and create a key.',
      'Paste it above — it saves automatically.',
    ],
    links: [{ label: 'api.together.ai', url: 'https://api.together.ai/settings/api-keys' }],
  },
  {
    id: 'copilot',
    label: 'GitHub Copilot (GitHub token)',
    kind: 'api-key',
    credentialLabel: 'GitHub Token',
    credentialDbKey: 'ai.copilot_gh_token',
    placeholder: 'Enter GitHub token (gho-… / ghu-… / github_pat-…)',
    hint: 'Needs Copilot access: OAuth token (gho-…), Copilot extension token (ghu-…), or fine-grained PAT (github_pat-…). Classic ghp_* tokens are rejected by the Copilot API. Or set GH_TOKEN in the environment.',
    requiresSubscription: 'Requires an active GitHub Copilot subscription.',
    steps: [
      'Create a token: GitHub → Settings → Developer settings → Personal access tokens → fine-grained token with Copilot access (github_pat-…); or run `gh auth login` (gho-…); or copy the Copilot extension OAuth token (ghu-…).',
      'Paste it above — it is exchanged automatically for a short-lived inference token (no CLI needed).',
      'Classic ghp_* tokens are rejected by the Copilot API.',
    ],
    links: [{ label: 'GitHub token settings', url: 'https://github.com/settings/tokens' }],
  },
  {
    id: 'codex',
    label: 'OpenAI Codex (ChatGPT subscription)',
    kind: 'oauth',
    requiresSubscription: 'Requires an active ChatGPT Plus or Pro subscription. No CLI install needed.',
    steps: [
      'Click “Sign in with ChatGPT” below.',
      'Open the shown URL in your browser and enter the code.',
      'Wait for confirmation — tokens refresh automatically afterwards.',
    ],
    links: [],
  },
];

export const AI_PROVIDER_MAP: Record<string, AiProviderMeta> = Object.fromEntries(
  AI_PROVIDERS.map((p) => [p.id, p]),
);
