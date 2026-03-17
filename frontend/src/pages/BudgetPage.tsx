/**
 * BudgetPage — LLM cost tracking & cap management (Sprint 14b D3).
 * Route: /budget
 */
import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';

interface BudgetSummary {
  period: string;
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  turn_count: number;
}

interface BudgetCap {
  id: string | null;
  period: 'daily' | 'monthly';
  limit_usd: number;
  action: 'warn' | 'block';
}

interface ProviderPricing {
  id: string | null;
  provider_id: string;
  model: string;
  input_cost_per_1k: number;
  output_cost_per_1k: number;
}

interface TurnCost {
  turn_id: string;
  session_id: string;
  agent_id: string;
  provider_id: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  timestamp: string;
}

type Tab = 'overview' | 'caps' | 'pricing' | 'usage';

export default function BudgetPage() {
  const [tab, setTab] = useState<Tab>('overview');
  const [dailySummary, setDailySummary] = useState<BudgetSummary | null>(null);
  const [monthlySummary, setMonthlySummary] = useState<BudgetSummary | null>(null);
  const [caps, setCaps] = useState<BudgetCap[]>([]);
  const [pricing, setPricing] = useState<ProviderPricing[]>([]);
  const [usage, setUsage] = useState<TurnCost[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Cap form state
  const [capPeriod, setCapPeriod] = useState<'daily' | 'monthly'>('daily');
  const [capLimit, setCapLimit] = useState('');
  const [capAction, setCapAction] = useState<'warn' | 'block'>('warn');
  const [capSaving, setCapSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const today = new Date().toISOString().slice(0, 10);
      const month = today.slice(0, 7);
      const [daily, monthly, capsData, pricingData, usageData] = await Promise.all([
        api.get<BudgetSummary>(`/budget/summary?period=daily&date_or_month=${today}`),
        api.get<BudgetSummary>(`/budget/summary?period=monthly&date_or_month=${month}`),
        api.get<BudgetCap[]>('/budget/caps'),
        api.get<ProviderPricing[]>('/budget/pricing'),
        api.get<TurnCost[]>('/budget/usage?limit=50'),
      ]);
      setDailySummary(daily);
      setMonthlySummary(monthly);
      setCaps(capsData);
      setPricing(pricingData);
      setUsage(usageData);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveCap = async () => {
    const limitVal = parseFloat(capLimit);
    if (isNaN(limitVal) || limitVal <= 0) {
      setError('Enter a positive number for the limit.');
      return;
    }
    setCapSaving(true);
    try {
      await api.put(`/budget/caps/${capPeriod}`, { limit_usd: limitVal, action: capAction });
      await load();
      setCapLimit('');
    } catch (e) {
      setError(String(e));
    } finally {
      setCapSaving(false);
    }
  };

  const deleteCap = async (period: string) => {
    try {
      await api.delete(`/budget/caps/${period}`);
      await load();
    } catch (e) {
      setError(String(e));
    }
  };

  const tabs: Tab[] = ['overview', 'caps', 'pricing', 'usage'];

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <h2 style={{ marginBottom: 16 }}>💰 Budget & Cost Tracking</h2>

      {error && (
        <div style={{ color: '#ef4444', marginBottom: 12, padding: 10, background: '#fef2f2', borderRadius: 6 }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: tab === t ? 'var(--color-primary, #6366f1)' : 'var(--color-surface-alt)',
              color: tab === t ? '#fff' : 'var(--color-on-surface)',
              fontWeight: tab === t ? 600 : 400, textTransform: 'capitalize',
            }}
          >
            {t}
          </button>
        ))}
        <button onClick={load} style={{ marginLeft: 'auto', padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', background: 'var(--color-surface-alt)', color: 'var(--color-on-surface)' }}>
          ↻ Refresh
        </button>
      </div>

      {loading && <div style={{ color: 'var(--color-on-muted)' }}>Loading…</div>}

      {tab === 'overview' && !loading && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {[dailySummary, monthlySummary].map((summary, i) => (
            summary && (
              <div
                key={i}
                style={{ padding: 20, borderRadius: 10, background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
              >
                <h3 style={{ marginBottom: 12, textTransform: 'capitalize' }}>{summary.period}</h3>
                <SummaryRow label="Total cost" value={`$${summary.total_cost_usd.toFixed(4)}`} highlight />
                <SummaryRow label="Turns" value={String(summary.turn_count)} />
                <SummaryRow label="Input tokens" value={summary.total_input_tokens.toLocaleString()} />
                <SummaryRow label="Output tokens" value={summary.total_output_tokens.toLocaleString()} />
              </div>
            )
          ))}
        </div>
      )}

      {tab === 'caps' && (
        <div>
          <div style={{ marginBottom: 20, padding: 16, borderRadius: 8, background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <h3 style={{ marginBottom: 12 }}>Set Cap</h3>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13 }}>
                Period
                <select value={capPeriod} onChange={(e) => setCapPeriod(e.target.value as 'daily' | 'monthly')} style={inputStyle}>
                  <option value="daily">Daily</option>
                  <option value="monthly">Monthly</option>
                </select>
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13 }}>
                Limit (USD)
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={capLimit}
                  onChange={(e) => setCapLimit(e.target.value)}
                  style={inputStyle}
                  placeholder="e.g. 5.00"
                />
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13 }}>
                Action
                <select value={capAction} onChange={(e) => setCapAction(e.target.value as 'warn' | 'block')} style={inputStyle}>
                  <option value="warn">Warn at 80%</option>
                  <option value="block">Block at 100%</option>
                </select>
              </label>
              <button
                onClick={saveCap}
                disabled={capSaving}
                style={{ padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer', background: 'var(--color-primary, #6366f1)', color: '#fff' }}
              >
                {capSaving ? 'Saving…' : 'Save Cap'}
              </button>
            </div>
          </div>

          <h3 style={{ marginBottom: 10 }}>Active Caps</h3>
          {caps.length === 0 && <div style={{ color: 'var(--color-on-muted)', fontStyle: 'italic' }}>No caps configured.</div>}
          {caps.map((cap) => (
            <div
              key={cap.period}
              style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', borderRadius: 8, background: 'var(--color-surface)', border: '1px solid var(--color-border)', marginBottom: 8 }}
            >
              <span style={{ fontWeight: 600, textTransform: 'capitalize', flex: 1 }}>{cap.period}</span>
              <span>${cap.limit_usd.toFixed(2)} / </span>
              <span style={{ color: cap.action === 'block' ? '#ef4444' : '#f59e0b', fontWeight: 600 }}>{cap.action}</span>
              <button
                onClick={() => deleteCap(cap.period)}
                style={{ padding: '3px 12px', borderRadius: 5, border: 'none', cursor: 'pointer', background: '#fef2f2', color: '#ef4444' }}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}

      {tab === 'pricing' && (
        <div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
                {['Provider', 'Model', 'Input $/1k', 'Output $/1k'].map((h) => (
                  <th key={h} style={{ padding: '6px 10px', textAlign: 'left', color: 'var(--color-on-muted)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pricing.map((p, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <td style={{ padding: '5px 10px' }}>{p.provider_id}</td>
                  <td style={{ padding: '5px 10px', fontFamily: 'monospace' }}>{p.model}</td>
                  <td style={{ padding: '5px 10px' }}>${p.input_cost_per_1k.toFixed(5)}</td>
                  <td style={{ padding: '5px 10px' }}>${p.output_cost_per_1k.toFixed(5)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'usage' && (
        <div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
                {['Time', 'Session', 'Agent', 'Model', 'In', 'Out', 'Cost'].map((h) => (
                  <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: 'var(--color-on-muted)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {usage.map((tc) => (
                <tr key={tc.turn_id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <td style={{ padding: '4px 8px', whiteSpace: 'nowrap' }}>{new Date(tc.timestamp).toLocaleString()}</td>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace', fontSize: 11 }}>{tc.session_id.slice(0, 8)}…</td>
                  <td style={{ padding: '4px 8px' }}>{tc.agent_id}</td>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>{tc.model}</td>
                  <td style={{ padding: '4px 8px' }}>{tc.input_tokens}</td>
                  <td style={{ padding: '4px 8px' }}>{tc.output_tokens}</td>
                  <td style={{ padding: '4px 8px', fontWeight: 600 }}>${tc.cost_usd.toFixed(5)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {usage.length === 0 && <div style={{ color: 'var(--color-on-muted)', fontStyle: 'italic', padding: 16 }}>No cost data yet.</div>}
        </div>
      )}
    </div>
  );
}

function SummaryRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 14 }}>
      <span style={{ color: 'var(--color-on-muted)' }}>{label}</span>
      <strong style={{ color: highlight ? 'var(--color-primary, #6366f1)' : 'var(--color-on-surface)' }}>{value}</strong>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)',
  background: 'var(--color-surface)', color: 'var(--color-on-surface)', fontSize: 13,
};
