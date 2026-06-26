const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8326";

export interface SoulProfile {
  dimensions: Record<string, string>;
}

export interface Settings {
  llm: { base_url: string; model: string; api_key: string };
  log_level: string;
}

export interface SceneOption {
  key: string;
  label: string;
  description: string;
  prompt: string;
}

export interface CircumstancesData {
  content: string;
  scene: string;
  scenes: SceneOption[];
}

export async function fetchCircumstances(): Promise<CircumstancesData> {
  const res = await fetch(`${BASE}/soul/circumstances`);
  if (!res.ok) throw new Error(`Failed to fetch circumstances: ${res.status}`);
  return res.json();
}

export async function updateCircumstances(content: string): Promise<void> {
  const res = await fetch(`${BASE}/soul/circumstances`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed to update circumstances: ${res.status}`);
}

export async function fetchSettings(): Promise<Settings> {
  const res = await fetch(`${BASE}/settings`);
  if (!res.ok) throw new Error(`Failed to fetch settings: ${res.status}`);
  return res.json();
}

export async function updateSettings(data: Partial<{ llm: Record<string, string>; voice: Record<string, string>; log_level: string }>) {
  const res = await fetch(`${BASE}/settings`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  if (!res.ok) throw new Error(`Failed to update settings: ${res.status}`);
}

export async function fetchVoiceStatus(): Promise<{ has_reference: boolean }> {
  const res = await fetch(`${BASE}/settings/voice/status`);
  if (!res.ok) throw new Error(`Failed to fetch voice status: ${res.status}`);
  return res.json();
}

export async function uploadVoiceSample(audioBlob: Blob): Promise<void> {
  const formData = new FormData();
  formData.append("audio", audioBlob, "reference.wav");
  formData.append("name", "soul_voice");
  const res = await fetch(`${BASE}/settings/voice/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    throw new Error((detail.detail as string) || `声纹上传失败: ${res.status}`);
  }
}

export async function testLLMConnection(): Promise<boolean> {
  const res = await fetch(`${BASE}/settings/test-llm`, { method: "POST" });
  if (!res.ok) return false;
  const data = await res.json();
  return data.connected;
}

export async function fetchSoul(): Promise<SoulProfile> {
  const res = await fetch(`${BASE}/soul`);
  if (!res.ok) throw new Error(`Failed to fetch soul: ${res.status}`);
  return res.json();
}

export async function fetchDimension(dimension: string): Promise<string> {
  const res = await fetch(`${BASE}/soul/${dimension}`);
  if (!res.ok) throw new Error(`Failed to fetch dimension: ${res.status}`);
  const data = await res.json();
  return data.content;
}

export async function updateDimension(dimension: string, content: string) {
  const res = await fetch(`${BASE}/soul/${dimension}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed to update dimension: ${res.status}`);
}

export interface ChatResponse {
  responseText: string;
  hasVoice: boolean;
  audioParams: { text: string; instructText: string };
}

export async function sendTextMessage(message: string): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})) as Record<string, unknown>;
    throw new Error((detail.detail as string) || `对话失败 (${res.status})`);
  }
  const data = await res.json();
  return {
    responseText: data.response_text,
    hasVoice: data.has_voice,
    audioParams: { text: data.response_text, instructText: data.instruct_text },
  };
}

export async function sendVoiceMessage(audioBlob: Blob): Promise<ChatResponse> {
  const formData = new FormData();
  formData.append("audio", audioBlob, "recording.wav");
  const res = await fetch(`${BASE}/chat/voice`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})) as Record<string, unknown>;
    throw new Error((detail.detail as string) || `语音对话失败 (${res.status})`);
  }
  const data = await res.json();
  return {
    responseText: data.response_text,
    hasVoice: data.has_voice,
    audioParams: { text: data.response_text, instructText: data.instruct_text },
  };
}

export interface HistoryMessage {
  role: string;
  content: string;
}

export async function fetchHistory(): Promise<HistoryMessage[]> {
  const res = await fetch(`${BASE}/chat/history`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.messages || [];
}

export async function deleteHistory(): Promise<void> {
  const res = await fetch(`${BASE}/chat/history`, { method: "DELETE" });
  if (!res.ok) throw new Error(`删除会话失败 (${res.status})`);
}

export async function fetchAudio(audioParams: { text: string; instructText: string }): Promise<Blob> {
  const res = await fetch(`${BASE}/chat/audio`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: audioParams.text, instruct_text: audioParams.instructText }),
  });
  if (!res.ok) throw new Error(`音频合成失败 (${res.status})`);
  return res.blob();
}

export function playAudioBlob(blob: Blob) {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  audio.play().catch(console.error);
}

export interface DistillResult {
  changes: string[];
  profile: Record<string, string>;
  summary: string;
  skill_card?: Record<string, string>;
}

export async function fetchSkill(): Promise<Record<string, string> | null> {
  const res = await fetch(`${BASE}/soul/skill`);
  if (!res.ok) return null;
  const data = await res.json();
  return data.skill_card || null;
}

export interface MemoryEntry {
  id: string;
  document: string;
  metadata: {
    dimension: string;
    strength: number;
    last_accessed_at: string;
    access_count: number;
    [key: string]: unknown;
  };
}

export interface MemoryStats {
  total: number;
  by_dimension: Record<string, number>;
}

export async function fetchMemoryStats(): Promise<MemoryStats> {
  const res = await fetch(`${BASE}/memory/stats`);
  if (!res.ok) throw new Error(`Failed to fetch memory stats: ${res.status}`);
  return res.json();
}

export async function fetchMemoryByDimension(dimension: string): Promise<MemoryEntry[]> {
  const res = await fetch(`${BASE}/memory/${encodeURIComponent(dimension)}`);
  if (!res.ok) throw new Error(`Failed to fetch memory: ${res.status}`);
  return res.json();
}

export async function deleteMemory(id: string): Promise<void> {
  const res = await fetch(`${BASE}/memory/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete memory: ${res.status}`);
}

export async function distillSoul(file: File, chatName?: string): Promise<DistillResult> {
  const formData = new FormData();
  formData.append("file", file);
  if (chatName) formData.append("chat_name", chatName);
  const res = await fetch(`${BASE}/soul/distill`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    throw new Error((detail.detail as string) || `蒸馏失败 (${res.status})`);
  }
  return res.json();
}
