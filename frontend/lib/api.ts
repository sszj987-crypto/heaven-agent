const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8326";

export interface SoulProfile {
  dimensions: Record<string, string>;
}

export interface Settings {
  llm: { base_url: string; model: string; api_key: string };
  voice: { fish_speech_url: string };
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

export async function updateSettings(data: Partial<{ llm: Record<string, string>; voice: Record<string, string> }>) {
  const res = await fetch(`${BASE}/settings`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  if (!res.ok) throw new Error(`Failed to update settings: ${res.status}`);
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

export async function sendTextMessage(message: string): Promise<{ audioBlob: Blob; responseText: string }> {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(`Chat failed: ${res.status}`);
  const audioBlob = await res.blob();
  const responseText = res.headers.get("X-Response-Text") || "";
  return { audioBlob, responseText };
}

export async function sendVoiceMessage(audioBlob: Blob): Promise<{ audioBlob: Blob; responseText: string }> {
  const formData = new FormData();
  formData.append("audio", audioBlob, "recording.wav");
  const res = await fetch(`${BASE}/chat/voice`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error(`Voice chat failed: ${res.status}`);
  const respAudioBlob = await res.blob();
  const responseText = res.headers.get("X-Response-Text") || "";
  return { audioBlob: respAudioBlob, responseText };
}

export function playAudioBlob(blob: Blob) {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  audio.play().catch(console.error);
}
