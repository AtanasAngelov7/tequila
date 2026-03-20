/**
 * SetupWizard — multi-step first-run wizard (§15.1).
 *
 * Steps:
 *   0  Welcome
 *   1  Provider selection
 *   2  API key + validation
 *   3  Model selection
 *   4  Agent creation
 *   5  Done → redirect to chat
 *
 * The wizard posts to POST /api/setup when the user completes step 4,
 * then calls onComplete() so the router can redirect to the main app.
 */
import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import SessionCaptureFlow from '../components/SessionCaptureFlow';

interface Props {
  onComplete: () => void;
}

type Provider = 'anthropic' | 'openai' | 'gemini' | 'ollama';
type AuthMode = 'api_key' | 'web_session';

// Web counterpart provider id for each api-key provider
const WEB_PROVIDER: Partial<Record<Provider, string>> = {
  anthropic: 'anthropic_web',
  openai: 'openai_web',
  gemini: 'gemini_web',
};

interface ModelItem {
  id: string;
  name: string;
}

const STEP_LABELS = [
  'Welcome',
  'Provider',
  'API Key',
  'Model',
  'Agent',
  'Done',
];

export default function SetupWizard({ onComplete }: Props) {
  const [step, setStep] = useState(0);

  // Step 0 — Welcome
  const [userName, setUserName] = useState('');

  // Step 1 — Provider
  const [provider, setProvider] = useState<Provider>('anthropic');
  const [authMode, setAuthMode] = useState<AuthMode>('api_key');

  // Web session capture state
  const [webSessionDone, setWebSessionDone] = useState(false);

  // Step 2 — API key
  const [apiKey, setApiKey] = useState('');
  const [keyValidation, setKeyValidation] = useState<{ valid: boolean; message: string } | null>(null);
  const [validating, setValidating] = useState(false);

  // Step 3 — Model
  const [models, setModels] = useState<ModelItem[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [loadingModels, setLoadingModels] = useState(false);

  // Step 4 — Agent
  const [agentName, setAgentName] = useState('Tequila');
  const [agentPersona, setAgentPersona] = useState('');

  // Step 5 — Submitting
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');

  // Load models when entering step 3
  useEffect(() => {
    if (step === 3) {
      setLoadingModels(true);
      api
        .get<{ models: ModelItem[] }>(`/setup/models/${provider}`)
        .then((data) => {
          setModels(data.models);
          if (data.models.length > 0) setSelectedModel(data.models[0].id);
        })
        .catch(() => setModels([]))
        .finally(() => setLoadingModels(false));
    }
  }, [step, provider]);

  const validateKey = async () => {
    if (provider === 'ollama') {
      setKeyValidation({ valid: true, message: 'Ollama runs locally — no key required.' });
      return;
    }
    if (!apiKey.trim()) {
      setKeyValidation({ valid: false, message: 'Please enter an API key.' });
      return;
    }
    setValidating(true);
    try {
      // Light client-side validation (mirrors backend stub)
      if (provider === 'anthropic' && !apiKey.startsWith('sk-ant-')) {
        setKeyValidation({
          valid: false,
          message: "Anthropic keys start with 'sk-ant-'. Check your key.",
        });
      } else if (provider === 'openai' && !apiKey.startsWith('sk-')) {
        setKeyValidation({
          valid: false,
          message: "OpenAI keys start with 'sk-'. Check your key.",
        });
      } else if (provider === 'gemini' && !apiKey.startsWith('AIza')) {
        setKeyValidation({
          valid: false,
          message: "Gemini keys start with 'AIza'. Check your key.",
        });
      } else {
        setKeyValidation({ valid: true, message: 'Key accepted.' });
      }
    } finally {
      setValidating(false);
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitError('');
    try {
      await api.post('/setup', {
        user_name: userName,
        provider,
        api_key: apiKey || null,
        auth_mode: authMode,
        default_model: selectedModel,
        agent_name: agentName,
        agent_persona: agentPersona || null,
      });
      setStep(5);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setSubmitError(e?.message ?? 'Setup failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  // ── Render ──────────────────────────────────────────────────────────

  return (
    <div style={overlayStyle}>
      <div style={cardStyle}>
        {/* Progress bar */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            {STEP_LABELS.map((label, i) => (
              <span
                key={label}
                style={{
                  fontSize: 10,
                  fontWeight: i === step ? 700 : 400,
                  color: i < step
                    ? 'var(--color-primary)'
                    : i === step
                    ? 'var(--color-on-surface)'
                    : 'var(--color-on-surface)',
                  opacity: i > step ? 0.35 : 1,
                }}
              >
                {label}
              </span>
            ))}
          </div>
          <div
            style={{
              height: 4,
              background: 'var(--color-border)',
              borderRadius: 2,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${((step) / (STEP_LABELS.length - 1)) * 100}%`,
                background: 'var(--color-primary)',
                borderRadius: 2,
                transition: 'width 0.3s ease',
              }}
            />
          </div>
        </div>

        {/* ── Step 0: Welcome ────────────────────────────────────────── */}
        {step === 0 && (
          <div>
            <h1 style={headingStyle}>Hi! What's your name? 👋</h1>
            <p style={subtitleStyle}>
              I'm Tequila, your personal AI assistant. I'll use your name to personalise our conversations.
            </p>
            <input
              autoFocus
              value={userName}
              onChange={(e) => setUserName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && userName.trim() && setStep(1)}
              placeholder="Your name…"
              style={inputStyle}
            />
            <div style={btnRowStyle}>
              <button
                onClick={() => setStep(1)}
                disabled={!userName.trim()}
                style={{ ...primaryBtnStyle, opacity: userName.trim() ? 1 : 0.45 }}
              >
                Get started →
              </button>
            </div>
          </div>
        )}

        {/* ── Step 1: Provider ───────────────────────────────────────── */}
        {step === 1 && (
          <div>
            <h2 style={headingStyle}>Choose your AI provider</h2>
            <p style={subtitleStyle}>
              Select the provider you want to use. You can change this later.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
              {(
                [
                  { id: 'anthropic', label: 'Anthropic', sub: 'Claude models — recommended' },
                  { id: 'openai', label: 'OpenAI', sub: 'GPT-5.4 models' },
                  { id: 'gemini', label: 'Google Gemini', sub: 'Gemini 2.5 & 3 models' },
                  { id: 'ollama', label: 'Ollama', sub: 'Local models — no API key needed' },
                ] as { id: Provider; label: string; sub: string }[]
              ).map((p) => (
                <button
                  key={p.id}
                  onClick={() => setProvider(p.id)}
                  style={{
                    ...providerCardStyle,
                    borderColor:
                      provider === p.id ? 'var(--color-primary)' : 'var(--color-border)',
                    background:
                      provider === p.id ? 'var(--color-primary)11' : 'var(--color-surface)',
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{p.label}</div>
                  <div style={{ fontSize: 12, opacity: 0.65 }}>{p.sub}</div>
                </button>
              ))}
            </div>
            <div style={btnRowStyle}>
              <button onClick={() => setStep(0)} style={secondaryBtnStyle}>← Back</button>
              <button onClick={() => setStep(2)} style={primaryBtnStyle}>Continue →</button>
            </div>
          </div>
        )}

        {/* ── Step 2: Auth Mode + Key / Session ─────────────────────── */}
        {step === 2 && (
          <div>
            <h2 style={headingStyle}>
              {provider === 'ollama' ? 'No API key needed' : 'Connect your account'}
            </h2>

            {provider === 'ollama' ? (
              <p style={subtitleStyle}>
                Ollama runs locally on your machine. Make sure it's running at{' '}
                <code>http://localhost:11434</code> before continuing.
              </p>
            ) : (
              <>
                {/* Auth mode toggle */}
                <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
                  {(['api_key', 'web_session'] as AuthMode[]).map((mode) => (
                    <button
                      key={mode}
                      onClick={() => { setAuthMode(mode); setKeyValidation(null); setWebSessionDone(false); }}
                      style={{
                        padding: '7px 16px',
                        borderRadius: 6,
                        border: `1px solid ${authMode === mode ? 'var(--color-primary)' : 'var(--color-border)'}`,
                        background: authMode === mode ? 'var(--color-primary)11' : 'transparent',
                        color: authMode === mode ? 'var(--color-primary)' : 'var(--color-on-surface)',
                        cursor: 'pointer',
                        fontSize: 13,
                        fontWeight: authMode === mode ? 600 : 400,
                      }}
                    >
                      {mode === 'api_key' ? '🔑 I have an API key' : '🌐 I have a subscription'}
                    </button>
                  ))}
                </div>

                {authMode === 'api_key' ? (
                  <>
                    <p style={subtitleStyle}>
                      {provider === 'anthropic'
                        ? 'Find your key at console.anthropic.com → API Keys.'
                        : provider === 'openai'
                        ? 'Find your key at platform.openai.com → API keys.'
                        : 'Find your key at aistudio.google.com → Get API key.'}
                    </p>
                    <label style={labelStyle}>
                      {provider === 'anthropic' ? 'Anthropic' : provider === 'openai' ? 'OpenAI' : 'Gemini'} API key
                    </label>
                    <input
                      type="password"
                      autoFocus
                      value={apiKey}
                      onChange={(e) => { setApiKey(e.target.value); setKeyValidation(null); }}
                      placeholder={
                        provider === 'anthropic' ? 'sk-ant-...' :
                        provider === 'openai' ? 'sk-...' : 'AIza...'
                      }
                      style={inputStyle}
                    />
                    <button
                      onClick={validateKey}
                      disabled={validating || !apiKey.trim()}
                      style={{ ...secondaryBtnStyle, marginBottom: 12 }}
                    >
                      {validating ? 'Checking…' : 'Validate key'}
                    </button>
                  </>
                ) : (
                  /* Web session capture */
                  WEB_PROVIDER[provider] && (
                    <div style={{ marginBottom: 16 }}>
                      <SessionCaptureFlow
                        provider={WEB_PROVIDER[provider]!}
                        providerLabel={
                          provider === 'anthropic' ? 'Anthropic' :
                          provider === 'openai' ? 'OpenAI' : 'Google Gemini'
                        }
                        onSuccess={() => setWebSessionDone(true)}
                      />
                    </div>
                  )
                )}
              </>
            )}

            {keyValidation && authMode === 'api_key' && (
              <div
                style={{
                  padding: '8px 12px',
                  borderRadius: 6,
                  fontSize: 13,
                  marginBottom: 12,
                  background: keyValidation.valid ? '#16a34a22' : '#dc262622',
                  color: keyValidation.valid ? '#16a34a' : '#dc2626',
                  border: `1px solid ${keyValidation.valid ? '#16a34a55' : '#dc262655'}`,
                }}
              >
                {keyValidation.valid ? '✓ ' : '✗ '}
                {keyValidation.message}
              </div>
            )}

            <div style={btnRowStyle}>
              <button onClick={() => setStep(1)} style={secondaryBtnStyle}>← Back</button>
              <button
                onClick={() => {
                  if (provider === 'ollama') {
                    setStep(3);
                  } else if (authMode === 'web_session') {
                    if (webSessionDone) setStep(3);
                  } else if (keyValidation?.valid) {
                    setStep(3);
                  } else {
                    validateKey().then(() => {/* transition on next interaction */});
                  }
                }}
                disabled={
                  provider !== 'ollama' &&
                  authMode === 'api_key' &&
                  !apiKey.trim()
                  || (provider !== 'ollama' && authMode === 'web_session' && !webSessionDone)
                }
                style={{
                  ...primaryBtnStyle,
                  opacity:
                    provider !== 'ollama' &&
                    authMode === 'api_key' &&
                    !apiKey.trim()
                      ? 0.45
                      : provider !== 'ollama' && authMode === 'web_session' && !webSessionDone
                      ? 0.45
                      : 1,
                }}
              >
                {provider !== 'ollama' && authMode === 'web_session' && !webSessionDone
                  ? 'Connect first →'
                  : 'Continue →'}
              </button>
            </div>
          </div>
        )}

        {/* ── Step 3: Model ──────────────────────────────────────────── */}
        {step === 3 && (
          <div>
            <h2 style={headingStyle}>Select default model</h2>
            <p style={subtitleStyle}>
              Choose the model Tequila will use by default. You can switch models per
              session later.
            </p>
            {loadingModels ? (
              <div style={{ opacity: 0.6, fontSize: 13, marginBottom: 24 }}>
                Loading models…
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
                {models.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => setSelectedModel(m.id)}
                    style={{
                      ...providerCardStyle,
                      borderColor:
                        selectedModel === m.id ? 'var(--color-primary)' : 'var(--color-border)',
                      background:
                        selectedModel === m.id
                          ? 'var(--color-primary)11'
                          : 'var(--color-surface)',
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{m.name}</div>
                    <div style={{ fontSize: 11, opacity: 0.55 }}>{m.id}</div>
                  </button>
                ))}
              </div>
            )}
            <div style={btnRowStyle}>
              <button onClick={() => setStep(2)} style={secondaryBtnStyle}>← Back</button>
              <button
                onClick={() => setStep(4)}
                disabled={!selectedModel}
                style={{ ...primaryBtnStyle, opacity: selectedModel ? 1 : 0.45 }}
              >
                Continue →
              </button>
            </div>
          </div>
        )}

        {/* ── Step 4: Agent ──────────────────────────────────────────── */}
        {step === 4 && (
          <div>
            <h2 style={headingStyle}>Create your main agent</h2>
            <p style={subtitleStyle}>
              Give your assistant a name and optional persona description.
            </p>
            <label style={labelStyle}>Agent name</label>
            <input
              autoFocus
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              placeholder="Tequila"
              style={inputStyle}
            />
            <label style={labelStyle}>Personality (optional)</label>
            <textarea
              value={agentPersona}
              onChange={(e) => setAgentPersona(e.target.value)}
              placeholder="Describe how you'd like your assistant to behave…"
              rows={3}
              style={{ ...inputStyle, resize: 'vertical' }}
            />
            {submitError && (
              <div
                style={{
                  padding: '8px 12px',
                  borderRadius: 6,
                  fontSize: 13,
                  marginBottom: 12,
                  background: '#dc262622',
                  color: '#dc2626',
                  border: '1px solid #dc262655',
                }}
              >
                ✗ {submitError}
              </div>
            )}
            <div style={btnRowStyle}>
              <button onClick={() => setStep(3)} style={secondaryBtnStyle} disabled={submitting}>
                ← Back
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting || !agentName.trim()}
                style={{
                  ...primaryBtnStyle,
                  opacity: submitting || !agentName.trim() ? 0.65 : 1,
                }}
              >
                {submitting ? 'Setting up…' : 'Finish setup →'}
              </button>
            </div>
          </div>
        )}

        {/* ── Step 5: Done ───────────────────────────────────────────── */}
        {step === 5 && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 64, marginBottom: 16 }}>🎉</div>
            <h2 style={headingStyle}>You're all set, {userName}!</h2>
            <p style={subtitleStyle}>
              Your agent <strong>{agentName}</strong> is ready to chat.
            </p>
            <button onClick={onComplete} style={{ ...primaryBtnStyle, marginTop: 8 }}>
              Start chatting →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Styles ──────────────────────────────────────────────────────────────────

const overlayStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  backgroundColor: 'var(--color-background)',
  padding: 24,
  zIndex: 1000,
};

const cardStyle: React.CSSProperties = {
  width: '100%',
  maxWidth: 480,
  backgroundColor: 'var(--color-surface)',
  borderRadius: 12,
  padding: '32px 36px',
  boxShadow: '0 8px 32px rgba(0,0,0,0.15)',
  border: '1px solid var(--color-border)',
};

const headingStyle: React.CSSProperties = {
  margin: '0 0 8px',
  fontSize: 22,
  fontWeight: 700,
  color: 'var(--color-on-surface)',
};

const subtitleStyle: React.CSSProperties = {
  margin: '0 0 20px',
  fontSize: 14,
  color: 'var(--color-on-surface)',
  opacity: 0.7,
  lineHeight: 1.5,
};

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 12,
  fontWeight: 600,
  marginBottom: 4,
  color: 'var(--color-on-surface)',
  opacity: 0.75,
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
};

const inputStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  padding: '9px 12px',
  fontSize: 14,
  border: '1px solid var(--color-border)',
  borderRadius: 6,
  backgroundColor: 'var(--color-background)',
  color: 'var(--color-on-surface)',
  marginBottom: 14,
  boxSizing: 'border-box',
  outline: 'none',
};

const btnRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'flex-end',
  gap: 8,
  marginTop: 8,
};

const primaryBtnStyle: React.CSSProperties = {
  padding: '9px 20px',
  backgroundColor: 'var(--color-primary)',
  color: '#fff',
  border: 'none',
  borderRadius: 7,
  cursor: 'pointer',
  fontSize: 14,
  fontWeight: 600,
};

const secondaryBtnStyle: React.CSSProperties = {
  padding: '9px 16px',
  backgroundColor: 'transparent',
  color: 'var(--color-on-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 7,
  cursor: 'pointer',
  fontSize: 14,
};

const providerCardStyle: React.CSSProperties = {
  padding: '12px 14px',
  textAlign: 'left',
  borderRadius: 8,
  border: '2px solid var(--color-border)',
  cursor: 'pointer',
  background: 'var(--color-surface)',
  color: 'var(--color-on-surface)',
  transition: 'border-color 0.15s, background 0.15s',
};
