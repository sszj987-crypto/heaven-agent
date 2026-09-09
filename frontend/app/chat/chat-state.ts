import type { ChatResponse, MemoryReference } from "@/lib/api";


export type ChatPhase = "idle" | "recording" | "transcribing" | "replying";
export type AudioState = "idle" | "loading" | "ready" | "error";

export type Message = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  audioParams?: { text: string; instructText: string };
  audioState?: AudioState;
  audioUrl?: string;
  audioError?: string;
  usedMemories?: MemoryReference[];
  safetyState?: "normal" | "supportive_redirect" | "crisis";
  responseId?: string;
  userMessage?: string;
  feedback?: "similar" | "dissimilar";
};

export function voicePhasePresentation(phase: ChatPhase): {
  side: "user" | "assistant" | null;
  label: string;
} {
  if (phase === "recording") {
    return { side: "user", label: "你正在说话…" };
  }
  if (phase === "transcribing") {
    return { side: "user", label: "正在识别你的语音…" };
  }
  if (phase === "replying") {
    return { side: "assistant", label: "正在回复…" };
  }
  return { side: null, label: "" };
}

export function createAssistantMessage(response: ChatResponse, userMessage = response.transcript): Message {
  return {
    id: crypto.randomUUID(),
    role: "assistant",
    content: response.responseText,
    audioParams: response.hasVoice ? response.audioParams : undefined,
    audioState: response.hasVoice ? "idle" : undefined,
    usedMemories: response.usedMemories,
    safetyState: response.safetyState,
    responseId: response.responseId,
    userMessage,
  };
}

export function withAudioState(
  message: Message,
  audioState: AudioState,
  audioError?: string,
): Message {
  return {
    ...message,
    audioState,
    audioError,
  };
}
