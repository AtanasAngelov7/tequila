// Sprint 04 — Agent API hook
import { useState, useCallback, useEffect } from 'react';
import { api } from '../api/client';

export interface SoulConfig {
  persona: string;
  instructions: string;
  system_prompt_template?: string | null;
  tone?: string;
  verbosity?: string;
  language?: string;
  emoji_usage?: boolean;
  prefer_markdown?: boolean;
  prefer_lists?: boolean;
  refuse_topics?: string[];
  escalation_phrases?: string[];
  metadata?: Record<string, unknown>;
}

export interface AgentConfig {
  agent_id: string;
  name: string;
  provider: string;
  default_model: string;
  persona: string;
  role: string;
  soul: SoulConfig | null;
  tools: string[];
  skills: string[];
  is_admin: boolean;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
}

interface AgentListResponse {
  agents: AgentConfig[];
  count: number;
}

interface CreateAgentRequest {
  name: string;
  provider?: string;
  default_model?: string;
  persona?: string;
  role?: string;
  is_admin?: boolean;
  soul?: Partial<SoulConfig>;
}

interface UpdateAgentRequest {
  version: number;
  name?: string;
  provider?: string;
  default_model?: string;
  persona?: string;
  role?: string;
  is_admin?: boolean;
  status?: string;
  soul?: Partial<SoulConfig>;
}

export function useAgents() {
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.get<AgentListResponse>('/agents');
      setAgents(resp.agents);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const createAgent = useCallback(async (data: CreateAgentRequest): Promise<AgentConfig> => {
    const agent = await api.post<AgentConfig>('/agents', data);
    setAgents((prev) => [...prev, agent]);
    return agent;
  }, []);

  const updateAgent = useCallback(
    async (agentId: string, data: UpdateAgentRequest): Promise<AgentConfig> => {
      const updated = await api.patch<AgentConfig>(`/agents/${agentId}`, data);
      setAgents((prev) => prev.map((a) => (a.agent_id === agentId ? updated : a)));
      return updated;
    },
    [],
  );

  const deleteAgent = useCallback(async (agentId: string): Promise<void> => {
    await api.delete(`/agents/${agentId}`);
    setAgents((prev) => prev.filter((a) => a.agent_id !== agentId));
  }, []);

  const cloneAgent = useCallback(async (agentId: string, name?: string): Promise<AgentConfig> => {
    const cloned = await api.post<AgentConfig>(`/agents/${agentId}/clone`, { name });
    setAgents((prev) => [...prev, cloned]);
    return cloned;
  }, []);

  const updateSoul = useCallback(
    async (agentId: string, version: number, soul: Partial<SoulConfig>): Promise<SoulConfig> => {
      const updated = await api.patch<AgentConfig>(`/agents/${agentId}`, {
        version,
        soul,
      });
      setAgents((prev) => prev.map((a) => (a.agent_id === agentId ? updated : a)));
      return updated.soul as SoulConfig;
    },
    [],
  );

  useEffect(() => {
    void fetchAgents();
  }, [fetchAgents]);

  return {
    agents,
    loading,
    error,
    fetchAgents,
    createAgent,
    updateAgent,
    deleteAgent,
    cloneAgent,
    updateSoul,
  };
}
