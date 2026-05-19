"use client";

import { useState, useRef, useCallback } from "react";
import { sendTextMessage, sendVoiceMessage, playAudioBlob } from "@/lib/api";

type Message = { role: "user" | "assistant"; content: string };

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const handleSendText = useCallback(async () => {
    if (!input.trim() || loading) return;
    const text = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const { audioBlob, responseText } = await sendTextMessage(text);
      setMessages((prev) => [...prev, { role: "assistant", content: responseText }]);
      if (audioBlob.size > 0) playAudioBlob(audioBlob);
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "[回复失败，请检查后端服务是否启动]" }]);
    } finally {
      setLoading(false);
    }
  }, [input, loading]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendText();
    }
  };

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(chunksRef.current, { type: "audio/webm" });
        stream.getTracks().forEach((t) => t.stop());
        if (audioBlob.size === 0) return;

        setLoading(true);
        try {
          const { audioBlob: respBlob, responseText } = await sendVoiceMessage(audioBlob);
          setMessages((prev) => [
            ...prev,
            { role: "user", content: "[语音消息]" },
            { role: "assistant", content: responseText },
          ]);
          if (respBlob.size > 0) playAudioBlob(respBlob);
        } catch {
          setMessages((prev) => [...prev, { role: "assistant", content: "[语音回复失败]" }]);
        } finally {
          setLoading(false);
        }
      };

      mediaRecorder.start();
      setRecording(true);
    } catch {
      alert("无法访问麦克风，请检查浏览器权限");
    }
  }, []);

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-57px)] max-w-2xl mx-auto w-full">
      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <p className="text-center text-white/20 mt-20">开始一段对话吧</p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                m.role === "user"
                  ? "bg-white/10 text-white/90"
                  : "bg-white/5 text-white/70 border border-white/10"
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-white/5 rounded-2xl px-4 py-3 text-sm text-white/30 animate-pulse">
              ...
            </div>
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className="border-t border-white/10 px-6 py-4 flex items-end gap-3">
        {/* 语音按钮 */}
        <button
          onMouseDown={startRecording}
          onMouseUp={stopRecording}
          onMouseLeave={stopRecording}
          onTouchStart={startRecording}
          onTouchEnd={stopRecording}
          disabled={loading}
          className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center transition-all ${
            recording
              ? "bg-red-500/80 scale-110 animate-pulse"
              : "bg-white/10 hover:bg-white/20"
          }`}
          title="按住说话"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
        </button>

        {/* 文字输入 */}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={recording ? "正在录音..." : "输入消息，Enter 发送"}
          disabled={loading || recording}
          className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm outline-none focus:border-white/30 transition-colors disabled:opacity-30"
        />

        {/* 发送按钮 */}
        <button
          onClick={handleSendText}
          disabled={loading || !input.trim()}
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
