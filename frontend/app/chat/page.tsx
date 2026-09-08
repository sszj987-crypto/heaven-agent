"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteHistory,
  fetchAudio,
  fetchHistory,
  sendTextMessage,
  sendVoiceMessage,
} from "@/lib/api";
import {
  createAssistantMessage,
  voicePhasePresentation,
  withAudioState,
  type ChatPhase,
  type Message,
} from "./chat-state";

function requestError(error: unknown, fallback: string): string {
  if (error instanceof TypeError && error.message === "Failed to fetch") {
    return "无法连接后端，请确认后端服务已启动 (localhost:8326)";
  }
  return error instanceof Error ? error.message : fallback;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [phase, setPhase] = useState<ChatPhase>("idle");
  const [interactionError, setInteractionError] = useState("");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const pressingRef = useRef(false);
  const chunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlsRef = useRef(new Set<string>());

  useEffect(() => {
    const objectUrls = objectUrlsRef.current;
    return () => {
      pressingRef.current = false;
      const recorder = mediaRecorderRef.current;
      if (recorder?.state === "recording") recorder.stop();
      audioRef.current?.pause();
      audioRef.current = null;
      objectUrls.forEach((url) => URL.revokeObjectURL(url));
      objectUrls.clear();
    };
  }, []);

  useEffect(() => {
    fetchHistory()
      .then((history) => {
        const restored: Message[] = history
          .filter((message) => message.role === "user" || message.role === "assistant")
          .map((message) => ({
            role: message.role as "user" | "assistant",
            content: message.content,
          }));
        if (restored.length > 0) setMessages(restored);
      })
      .catch(() => undefined);
  }, []);

  const updateMessage = useCallback(
    (index: number, update: (message: Message) => Message) => {
      setMessages((current) => current.map((message, itemIndex) =>
        itemIndex === index ? update(message) : message
      ));
    },
    [],
  );

  const playAudioUrl = useCallback((url: string, index: number) => {
    audioRef.current?.pause();
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onended = () => {
      if (audioRef.current === audio) audioRef.current = null;
    };
    audio.onerror = () => {
      if (audioRef.current === audio) audioRef.current = null;
      updateMessage(index, (message) =>
        withAudioState(message, "error", "语音播放失败，请重试")
      );
    };
    audio.play()
      .then(() => {
        updateMessage(index, (message) => withAudioState(message, "ready"));
      })
      .catch((error: unknown) => {
        if (audioRef.current === audio) audioRef.current = null;
        const blocked = error instanceof DOMException && error.name === "NotAllowedError";
        updateMessage(index, (message) => withAudioState(
          message,
          "error",
          blocked ? "语音已生成，请再次点击播放" : "语音播放失败，请重试",
        ));
      });
  }, [updateMessage]);

  const handlePlayAudio = useCallback(async (index: number) => {
    const message = messages[index];
    if (!message?.audioParams || message.audioState === "loading") return;

    if (message.audioUrl) {
      updateMessage(index, (current) => withAudioState(current, "ready"));
      playAudioUrl(message.audioUrl, index);
      return;
    }

    updateMessage(index, (current) => withAudioState(current, "loading"));
    try {
      const audioBlob = await fetchAudio(message.audioParams);
      const url = URL.createObjectURL(audioBlob);
      objectUrlsRef.current.add(url);
      updateMessage(index, (current) => ({
        ...withAudioState(current, "ready"),
        audioUrl: url,
      }));
      playAudioUrl(url, index);
    } catch (error) {
      updateMessage(index, (current) => withAudioState(
        current,
        "error",
        requestError(error, "语音生成失败，请重试"),
      ));
    }
  }, [messages, playAudioUrl, updateMessage]);

  const handleSendText = useCallback(async () => {
    if (!input.trim() || phase !== "idle") return;
    const text = input.trim();
    setInput("");
    setInteractionError("");
    setMessages((current) => [...current, { role: "user", content: text }]);
    setPhase("replying");

    try {
      const response = await sendTextMessage(text);
      setMessages((current) => [...current, createAssistantMessage(response)]);
    } catch (error) {
      setInteractionError(requestError(error, "回复失败，请重试"));
    } finally {
      setPhase("idle");
    }
  }, [input, phase]);

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSendText();
    }
  };

  const startRecording = useCallback(async () => {
    if (phase !== "idle") return;
    pressingRef.current = true;
    setInteractionError("");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!pressingRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      const webmSupported = typeof MediaRecorder.isTypeSupported === "function"
        && MediaRecorder.isTypeSupported("audio/webm");
      const recorder = new MediaRecorder(
        stream,
        webmSupported ? { mimeType: "audio/webm" } : undefined,
      );
      mediaRecorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };

      recorder.onerror = () => {
        stream.getTracks().forEach((track) => track.stop());
        mediaRecorderRef.current = null;
        pressingRef.current = false;
        setInteractionError("录音失败，请检查麦克风后重试");
        setPhase("idle");
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        mediaRecorderRef.current = null;
        const mimeType = recorder.mimeType || chunksRef.current[0]?.type || "audio/webm";
        const audioBlob = new Blob(chunksRef.current, { type: mimeType });
        chunksRef.current = [];

        if (audioBlob.size === 0) {
          setInteractionError("没有录到声音，请按住麦克风后再说话");
          setPhase("idle");
          return;
        }

        try {
          const response = await sendVoiceMessage(audioBlob);
          setMessages((current) => [
            ...current,
            { role: "user", content: response.transcript || "[未能显示语音转写]" },
            createAssistantMessage(response),
          ]);
        } catch (error) {
          setInteractionError(requestError(error, "语音识别失败，请重试"));
        } finally {
          setPhase("idle");
        }
      };

      recorder.start();
      setPhase("recording");
    } catch (error) {
      pressingRef.current = false;
      setPhase("idle");
      setInteractionError(requestError(error, "无法访问麦克风，请检查浏览器权限"));
    }
  }, [phase]);

  const stopRecording = useCallback(() => {
    pressingRef.current = false;
    const recorder = mediaRecorderRef.current;
    if (recorder?.state !== "recording") return;
    setPhase("transcribing");
    recorder.stop();
  }, []);

  const handleDelete = async () => {
    if (!confirm("确定要清空当前对话吗？原记录会归档到本地回收目录，可手工恢复。")) return;
    try {
      await deleteHistory();
      audioRef.current?.pause();
      audioRef.current = null;
      objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      objectUrlsRef.current.clear();
      setMessages([]);
      setInteractionError("");
      setPhase("idle");
    } catch {
      setInteractionError("删除失败，请重试");
    }
  };

  const phaseView = voicePhasePresentation(phase);
  const busy = phase !== "idle";

  return (
    <div className="chat-page">
      {messages.length > 0 && (
        <div className="flex shrink-0 justify-end px-8 py-3 border-b border-white/5">
          <button onClick={handleDelete} className="text-xs text-stone-400 hover:text-red-300 transition-colors px-2 py-1 rounded" title="删除会话">
            清空对话
          </button>
        </div>
      )}

      <div aria-label="对话消息" role="region" tabIndex={0} className="min-h-0 flex-1 overflow-y-auto px-8 py-6 space-y-5">
        {messages.length === 0 && phase === "idle" && (
          <p className="text-center text-white/20 mt-20">开始一段对话吧</p>
        )}

        {messages.map((message, index) => (
          <div key={index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[min(80%,720px)] [overflow-wrap:anywhere] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
              message.role === "user"
                ? "bg-white/10 text-white/90"
                : "bg-white/5 text-white/70 border border-white/10"
            }`}>
              <p>{message.content}</p>

              {message.role === "assistant" && message.audioParams && (
                <div className="mt-2">
                  <button
                    type="button"
                    onClick={() => void handlePlayAudio(index)}
                    disabled={message.audioState === "loading"}
                    className="inline-flex items-center gap-1.5 text-xs text-white/60 hover:text-white/90 disabled:text-white/30 transition-colors bg-white/5 hover:bg-white/10 rounded-full px-3 py-1"
                  >
                    {message.audioState === "loading" ? (
                      <span className="w-3 h-3 rounded-full border border-white/20 border-t-white/50 animate-spin" />
                    ) : (
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                        <polygon points="5,3 19,12 5,21" />
                      </svg>
                    )}
                    {message.audioState === "loading"
                      ? "正在生成语音…"
                      : message.audioState === "error"
                        ? "重试播放"
                        : "播放语音"}
                  </button>
                  {message.audioError && (
                    <p className="mt-1.5 text-xs text-amber-200/60">{message.audioError}</p>
                  )}
                </div>
              )}

              {message.role === "assistant" && message.usedMemories && message.usedMemories.length > 0 && (
                <details className="mt-3 border-t border-white/5 pt-2 text-xs text-white/30">
                  <summary className="cursor-pointer hover:text-white/50">
                    本次参考了 {message.usedMemories.length} 条记忆
                  </summary>
                  <ul className="mt-2 space-y-1.5">
                    {message.usedMemories.map((memory) => (
                      <li key={memory.id || memory.content} className="leading-5">· {memory.content}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          </div>
        ))}

        {phaseView.side && (
          <div className={`flex ${phaseView.side === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`rounded-2xl px-4 py-3 text-sm animate-pulse ${
              phaseView.side === "user"
                ? "bg-red-500/15 border border-red-400/20 text-red-100/70"
                : "bg-white/5 text-white/30"
            }`}>
              {phaseView.label}
            </div>
          </div>
        )}
      </div>

      {interactionError && (
        <div role="status" className="shrink-0 px-8 pb-2 text-center text-xs text-amber-200/60">{interactionError}</div>
      )}

      <div className="shrink-0 border-t border-white/10 px-8 py-5 flex items-end gap-3">
        <button
          type="button"
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            void startRecording();
          }}
          onPointerUp={stopRecording}
          onPointerCancel={stopRecording}
          disabled={phase !== "idle" && phase !== "recording"}
          className={`touch-none shrink-0 w-10 h-10 rounded-full flex items-center justify-center transition-all ${
            phase === "recording"
              ? "bg-red-500/80 scale-110 animate-pulse"
              : "bg-white/10 hover:bg-white/20 disabled:opacity-30"
          }`}
          title="按住说话"
          aria-label="按住说话"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
        </button>

        <input
          aria-label="消息内容"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            phase === "recording"
              ? "你正在说话…"
              : phase === "transcribing"
                ? "正在识别你的语音…"
                : phase === "replying"
                  ? "正在生成回复…"
                  : "输入消息，Enter 发送"
          }
          disabled={busy}
          className="min-w-0 flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm outline-none focus:border-white/30 transition-colors disabled:opacity-30"
        />

        <button
          type="button"
          onClick={() => void handleSendText()}
          aria-label="发送消息"
          disabled={busy || !input.trim()}
          className="shrink-0 w-10 h-10 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center disabled:opacity-20 transition-all"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  );
}
