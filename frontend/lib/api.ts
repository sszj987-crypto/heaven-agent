// The packaged desktop UI is served by the same local process as the API and
// deliberately supplies an empty value. Development keeps its explicit URL.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8326";

export function formatApiError(payload: unknown, status: number, fallback: string): string {
  if (payload && typeof payload === "object") {
    const body = payload as Record<string, unknown>;
    if (typeof body.message === "string" && body.message.trim()) return body.message;
    if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
  }
  return `${fallback} (${status})`;
}

async function apiError(res: Response, fallback: string): Promise<Error> {
  const payload: unknown = await res.json().catch(() => ({}));
  return new Error(formatApiError(payload, res.status, fallback));
}

export interface SoulProfile {
  dimensions: Record<string, string>;
}

export interface Settings {
  llm: {
    base_url: string;
    model: string;
    temperature: number | null;
    api_key_configured: boolean;
  };
  tts: TTSSettings;
  log_level: string;
}

export type TTSProvider = "local" | "minimax" | "openai_compatible";

export interface TTSSettings {
  provider: TTSProvider;
  auto_play: boolean;
  audio_cache_size: number;
  minimax: {
    base_url: string;
    model: string;
    api_key_configured: boolean;
  };
  openai_compatible: {
    base_url: string;
    model: string;
    voice: string;
    api_key_configured: boolean;
  };
}

export interface TTSSettingsUpdate {
  provider: TTSProvider;
  auto_play: boolean;
  audio_cache_size: number;
  minimax?: {
    base_url: string;
    model: string;
    api_key?: string;
  };
  openai_compatible?: {
    base_url: string;
    model: string;
    voice: string;
    api_key?: string;
  };
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
  if (!res.ok) throw await apiError(res, "无法读取场景设置");
  return res.json();
}

export async function updateCircumstances(content: string): Promise<void> {
  const res = await fetch(`${BASE}/soul/circumstances`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw await apiError(res, "无法更新场景设置");
}

export async function fetchSettings(): Promise<Settings> {
  const res = await fetch(`${BASE}/settings`);
  if (!res.ok) throw await apiError(res, "无法读取设置");
  return res.json();
}

export async function updateSettings(data: Partial<{
  llm: Partial<{ base_url: string; model: string; temperature: number; api_key: string }>;
  tts: TTSSettingsUpdate;
  log_level: string;
}>): Promise<void> {
  const res = await fetch(`${BASE}/settings`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  if (!res.ok) throw await apiError(res, "无法更新设置");
}

export interface VoiceStatus {
  provider: TTSProvider;
  state: "not_installed" | "not_configured" | "creating" | "failed" | "ready" | "no_voice";
  message: string;
  has_reference: boolean;
  ready: boolean;
  supports_instruction: boolean;
  supports_voice_cloning: boolean;
  preview_available: boolean;
}

export async function fetchVoiceStatus(): Promise<VoiceStatus> {
  const res = await fetch(`${BASE}/settings/voice/status`);
  if (!res.ok) throw await apiError(res, "无法读取声音状态");
  return res.json();
}

export type VoiceInstallState =
  | "not_installed"
  | "installing"
  | "restart_required"
  | "installed"
  | "failed";

export interface VoiceInstallationStatus {
  state: VoiceInstallState;
  stage: string;
  message: string;
  restart_required: boolean;
  job_id: string | null;
}

export async function fetchVoiceInstallation(): Promise<VoiceInstallationStatus> {
  const res = await fetch(`${BASE}/system/voice-installation`);
  if (!res.ok) throw await apiError(res, "无法读取语音组件状态");
  return res.json();
}

export async function installVoice(): Promise<string> {
  const res = await fetch(`${BASE}/system/voice-installation`, {
    method: "POST",
    headers: { "X-Heaven-Action": "install-voice" },
  });
  if (!res.ok) throw await apiError(res, "语音组件安装失败");
  const data = await res.json();
  return data.job_id;
}

export async function uploadVoiceSample(audioBlob: Blob): Promise<{ preview_available: boolean }> {
  const formData = new FormData();
  const extensions: Record<string, string> = {
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/webm": "webm", "audio/ogg": "ogg",
  };
  const filename = audioBlob instanceof File ? audioBlob.name
    : `reference.${extensions[audioBlob.type.split(";")[0]] || "bin"}`;
  formData.append("audio", audioBlob, filename);
  formData.append("name", "soul_voice");
  const res = await fetch(`${BASE}/settings/voice/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    throw await apiError(res, "声音上传失败");
  }
  return res.json();
}

export async function fetchVoicePreview(): Promise<Blob> {
  const res = await fetch(`${BASE}/settings/voice/preview`);
  if (!res.ok) throw await apiError(res, "无法读取试听音频");
  const blob = await res.blob();
  if (!blob.size) throw new Error("试听音频为空，请重新创建音色");
  return blob;
}

export async function testLLMConnection(): Promise<boolean> {
  const res = await fetch(`${BASE}/settings/test-llm`, { method: "POST" });
  if (!res.ok) return false;
  const data = await res.json();
  return data.connected;
}

export async function testTTSConnection(): Promise<boolean> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/settings/test-tts`, { method: "POST" });
  } catch {
    throw new Error("无法连接语音服务");
  }
  if (!res.ok) throw await apiError(res, "语音连接测试失败");
  try {
    const data = await res.json();
    if (typeof data?.connected !== "boolean") throw new Error();
    return data.connected;
  } catch {
    throw new Error("语音连接测试返回无效");
  }
}

export async function fetchSoul(): Promise<SoulProfile> {
  const res = await fetch(`${BASE}/soul`);
  if (!res.ok) throw await apiError(res, "无法读取人物档案");
  return res.json();
}

export async function fetchDimension(dimension: string): Promise<string> {
  const res = await fetch(`${BASE}/soul/${dimension}`);
  if (!res.ok) throw await apiError(res, "无法读取档案维度");
  const data = await res.json();
  return data.content;
}

export async function updateDimension(dimension: string, content: string) {
  const res = await fetch(`${BASE}/soul/${dimension}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw await apiError(res, "无法更新档案维度");
}

export interface ChatResponse {
  responseId: string;
  responseText: string;
  hasVoice: boolean;
  audioParams: { text: string; instructText: string };
  transcript?: string;
  usedMemories: MemoryReference[];
  safetyState: "normal" | "supportive_redirect" | "crisis";
  timing: ChatTiming;
}

export interface ChatTiming {
  firstResponseMs: number | null;
  totalResponseMs: number;
}

export interface MemoryReference {
  id: string;
  content: string;
  dimension: string;
  source_type: string;
}

export type FeedbackReason = "fact" | "style" | "relationship" | "response" | "other";

export async function saveChatFeedback(
  responseId: string,
  data: {
    userMessage: string;
    responseText: string;
    rating: "similar" | "dissimilar";
    reasons?: FeedbackReason[];
    suggestion?: string;
  },
): Promise<void> {
  const res = await fetch(`${BASE}/chat/feedback/${encodeURIComponent(responseId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_message: data.userMessage,
      response_text: data.responseText,
      rating: data.rating,
      reasons: data.reasons || [],
      suggestion: data.suggestion || "",
    }),
  });
  if (!res.ok) throw await apiError(res, "保存反馈失败");
}

export async function sendTextMessage(message: string): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    throw await apiError(res, "对话失败");
  }
  const data = await res.json();
  return {
    responseId: data.response_id,
    responseText: data.response_text,
    hasVoice: data.has_voice,
    audioParams: { text: data.response_text, instructText: data.instruct_text },
    usedMemories: data.used_memories || [],
    safetyState: data.safety_state || "normal",
    timing: {
      firstResponseMs: data.timing?.first_response_ms ?? null,
      totalResponseMs: data.timing?.total_response_ms ?? 0,
    },
  };
}

export type ChatStreamEvent =
  | { type: "delta"; content: string }
  | { type: "reset" }
  | { type: "done"; response_id: string; response_text: string; instruct_text: string; has_voice: boolean; used_memories: MemoryReference[]; safety_state: ChatResponse["safetyState"]; timing?: { first_response_ms?: number | null; total_response_ms?: number } }
  | { type: "error"; message: string };

export async function streamTextMessage(
  message: string,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!res.ok) throw await apiError(res, "对话失败");
  if (!res.body) throw new Error("浏览器不支持流式对话");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  let completed: ChatResponse | undefined;
  const consume = (packet: string) => {
    const data = packet.split("\n").find(line => line.startsWith("data: "))?.slice(6);
    if (!data) return;
    const event = JSON.parse(data) as ChatStreamEvent;
    onEvent(event);
    if (event.type === "error") throw new Error(event.message);
    if (event.type === "done") {
      completed = {
        responseId: event.response_id,
        responseText: event.response_text,
        hasVoice: event.has_voice,
        audioParams: { text: event.response_text, instructText: event.instruct_text },
        usedMemories: event.used_memories || [],
        safetyState: event.safety_state || "normal",
        timing: {
          firstResponseMs: event.timing?.first_response_ms ?? null,
          totalResponseMs: event.timing?.total_response_ms ?? 0,
        },
      };
    }
  };
  while (true) {
    const { value, done } = await reader.read();
    buffered += decoder.decode(value, { stream: !done });
    let separator;
    while ((separator = buffered.indexOf("\n\n")) >= 0) {
      consume(buffered.slice(0, separator));
      buffered = buffered.slice(separator + 2);
    }
    if (done) break;
  }
  if (buffered) consume(buffered);
  if (!completed) throw new Error("对话流意外结束，请重试");
  return completed;
}

export async function sendVoiceMessage(audioBlob: Blob, signal?: AbortSignal): Promise<ChatResponse> {
  const formData = new FormData();
  formData.append("audio", audioBlob, "recording.wav");
  const res = await fetch(`${BASE}/chat/voice`, {
    method: "POST",
    body: formData,
    signal,
  });
  if (!res.ok) {
    throw await apiError(res, "语音对话失败");
  }
  const data = await res.json();
  return {
    responseId: data.response_id,
    responseText: data.response_text,
    hasVoice: data.has_voice,
    audioParams: { text: data.response_text, instructText: data.instruct_text },
    transcript: data.transcript,
    usedMemories: data.used_memories || [],
    safetyState: data.safety_state || "normal",
    timing: {
      firstResponseMs: data.timing?.first_response_ms ?? null,
      totalResponseMs: data.timing?.total_response_ms ?? 0,
    },
  };
}

export interface SystemStatus {
  initialization: "ready" | "degraded";
  soul_id: string;
  soul_name: string;
  capabilities: {
    text_chat: boolean;
    voice_installed: boolean;
    voice_ready: boolean;
    tts_instruction: boolean;
    ffmpeg: boolean;
  };
  onboarding: {
    profile_ready: boolean;
    import_review_ready: boolean;
    voice_ready: boolean;
    completed: boolean;
  };
  pending_jobs: number;
  pending_candidates: number;
}

export async function fetchSystemStatus(): Promise<SystemStatus> {
  const res = await fetch(`${BASE}/system/status`);
  if (!res.ok) throw await apiError(res, "无法读取系统状态");
  return res.json();
}

export async function completeOnboarding(): Promise<SystemStatus> {
  const res = await fetch(`${BASE}/system/onboarding/complete`, { method: "POST" });
  if (!res.ok) throw await apiError(res, "无法完成首次设置");
  return res.json();
}

export type OnboardingStep = "profile" | "import_review" | "voice";

export async function markOnboardingStep(step: OnboardingStep): Promise<SystemStatus> {
  const res = await fetch(`${BASE}/system/onboarding/steps/${step}`, { method: "POST" });
  if (!res.ok) throw await apiError(res, "无法记录首次设置进度");
  return res.json();
}

export async function resetDemo(): Promise<string> {
  const res = await fetch(`${BASE}/system/demo-reset`, {
    method: "POST",
    headers: { "X-Heaven-Action": "demo-reset" },
  });
  if (!res.ok) throw await apiError(res, "无法重置演示数据");
  const data = await res.json();
  return data.backup;
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
  if (!res.ok) throw await apiError(res, "清空会话失败");
}

export async function fetchAudio(audioParams: { text: string; instructText: string }, signal?: AbortSignal): Promise<Blob> {
  const res = await fetch(`${BASE}/chat/audio`, {
    signal,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: audioParams.text, instruct_text: audioParams.instructText }),
  });
  if (!res.ok) throw await apiError(res, "音频合成失败");
  const blob = await res.blob();
  if (blob.size === 0) throw new Error("语音准备失败，请重试");
  return blob;
}

export interface DistillResult {
  changes: string[];
  profile: Record<string, string>;
  summary: string;
  skill_card?: Record<string, string>;
  candidate_ids?: string[];
  candidate_count?: number;
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

export interface MemoryCandidate {
  id: string;
  dimension: string;
  content: string;
  source_type: string;
  source_excerpt: string;
  confidence: number;
  source_speaker: string;
  status: "pending" | "approved" | "rejected";
  conflict_with?: string | null;
  created_at: string;
  resolved_at?: string | null;
}

export async function fetchMemoryCandidates(status = "pending"): Promise<MemoryCandidate[]> {
  const res = await fetch(`${BASE}/memory/candidates?status=${encodeURIComponent(status)}`);
  if (!res.ok) throw await apiError(res, "无法读取候选事实");
  return res.json();
}

export async function approveMemoryCandidate(id: string, content?: string): Promise<MemoryCandidate> {
  const res = await fetch(`${BASE}/memory/candidates/${encodeURIComponent(id)}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(content === undefined ? {} : { content }),
  });
  if (!res.ok) throw await apiError(res, "确认候选事实失败");
  return res.json();
}

export async function rejectMemoryCandidate(id: string): Promise<MemoryCandidate> {
  const res = await fetch(`${BASE}/memory/candidates/${encodeURIComponent(id)}/reject`, { method: "POST" });
  if (!res.ok) throw await apiError(res, "忽略候选事实失败");
  return res.json();
}

export interface JobStatus {
  id: string;
  kind: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  result?: DistillResult;
  error?: string | null;
}

export interface ImportSpeaker {
  name: string;
  message_count: number;
  matches_profile_name: boolean;
}

export async function previewSoulImport(file: File): Promise<ImportSpeaker[]> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${BASE}/soul/import-preview`, { method: "POST", body: formData });
  if (!res.ok) throw await apiError(res, "无法解析聊天记录");
  const data = await res.json();
  return data.speakers || [];
}

export async function createSoulImport(file: File, chatName: string): Promise<string> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("chat_name", chatName);
  const res = await fetch(`${BASE}/soul/imports`, { method: "POST", body: formData });
  if (!res.ok) throw await apiError(res, "创建导入任务失败");
  const data = await res.json();
  return data.job_id;
}

export async function fetchJob(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${BASE}/jobs/${encodeURIComponent(jobId)}`);
  if (!res.ok) throw await apiError(res, "无法读取任务状态");
  return res.json();
}

export async function fetchMemoryStats(): Promise<MemoryStats> {
  const res = await fetch(`${BASE}/memory/stats`);
  if (!res.ok) throw await apiError(res, "无法读取记忆统计");
  return res.json();
}

export async function fetchMemoryByDimension(dimension: string): Promise<MemoryEntry[]> {
  const res = await fetch(`${BASE}/memory/${encodeURIComponent(dimension)}`);
  if (!res.ok) throw await apiError(res, "无法读取记忆");
  return res.json();
}

export async function deleteMemory(id: string): Promise<void> {
  const res = await fetch(`${BASE}/memory/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw await apiError(res, "无法删除记忆");
}

export async function distillSoul(file: File, chatName: string): Promise<DistillResult> {
  const jobId = await createSoulImport(file, chatName);
  for (;;) {
    const job = await fetchJob(jobId);
    if (job.status === "completed" && job.result) return job.result;
    if (job.status === "failed") throw new Error(job.error || "导入分析失败");
    if (job.status === "cancelled") throw new Error("导入任务已取消");
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
}
