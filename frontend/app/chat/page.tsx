"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { sendTextMessage, sendVoiceMessage, fetchAudio, fetchHistory, deleteHistory } from "@/lib/api";

type Message = { role: "user" | "assistant"; content: string; audioUrl?: string; audioLoading?: boolean };

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  // 页面加载时从后端恢复对话历史
  useEffect(() => {
    fetchHistory().then((history) => {
      if (history.length > 0) {
        const msgs: Message[] = history
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
        if (msgs.length > 0) setMessages(msgs);
      }
    }).catch(() => {});
  }, []);

  const handleSendText = useCallback(async () => {
    if (!input.trim() || loading) return;
    const text = input.trim();
    setInput("");
    const msgIndex = messages.length;
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const { responseText, hasVoice, audioParams } = await sendTextMessage(text);
      // 立即显示文字回复
      setMessages((prev) => [...prev, { role: "assistant", content: responseText }]);
      setLoading(false);
      // 后台获取音频
      if (hasVoice) {
        const respIndex = msgIndex + 1;
        setMessages((prev) => prev.map((m, i) =>
          i === respIndex ? { ...m, audioLoading: true } : m
        ));
        try {
          const audioBlob = await fetchAudio(audioParams);
          const url = URL.createObjectURL(audioBlob);
          setMessages((prev) => prev.map((m, i) =>
            i === respIndex ? { ...m, audioUrl: url, audioLoading: false } : m
          ));
        } catch {
          setMessages((prev) => prev.map((m, i) =>
            i === respIndex ? { ...m, audioLoading: false } : m
          ));
        }
      }
    } catch (err) {
      const reason = err instanceof TypeError && err.message === "Failed to fetch"
        ? "无法连接后端，请确认后端服务已启动 (localhost:8326)"
        : (err instanceof Error ? err.message : "未知错误");
      setMessages((prev) => [...prev, { role: "assistant", content: `[回复失败] ${reason}` }]);
      setLoading(false);
    }
  }, [input, loading, messages.length]);

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
        const msgIndex = messages.length;
        try {
          const { responseText, hasVoice, audioParams } = await sendVoiceMessage(audioBlob);
          setMessages((prev) => [
            ...prev,
            { role: "user", content: "[语音消息]" },
            { role: "assistant", content: responseText },
          ]);
          setLoading(false);
          // 后台获取音频
          if (hasVoice) {
            const respIndex = msgIndex + 1;
            setMessages((prev) => prev.map((m, i) =>
              i === respIndex ? { ...m, audioLoading: true } : m
            ));
            try {
              const respBlob = await fetchAudio(audioParams);
              const url = URL.createObjectURL(respBlob);
              setMessages((prev) => prev.map((m, i) =>
                i === respIndex ? { ...m, audioUrl: url, audioLoading: false } : m
              ));
            } catch {
              setMessages((prev) => prev.map((m, i) =>
                i === respIndex ? { ...m, audioLoading: false } : m
              ));
            }
          }
        } catch {
          setMessages((prev) => [...prev, { role: "assistant", content: "[语音回复失败]" }]);
          setLoading(false);
        }
      };

      mediaRecorder.start();
      setRecording(true);
    } catch {
      alert("无法访问麦克风，请检查浏览器权限");
    }
  }, [messages.length]);

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  };

  const handleDelete = async () => {
    if (!confirm("确定要删除所有对话记录吗？此操作不可撤销。")) return;
    try {
      await deleteHistory();
      setMessages([]);
    } catch {
      alert("删除失败，请重试");
    }
  };

  const handlePlayAudio = (url: string) => {
    const audio = new Audio(url);
    audio.play().catch(console.error);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-57px)] max-w-2xl mx-auto w-full">
      {/* 顶部操作栏 */}
      {messages.length > 0 && (
        <div className="flex justify-end px-6 py-2 border-b border-white/5">
          <button
            onClick={handleDelete}
            className="text-xs text-white/20 hover:text-red-400/60 transition-colors px-2 py-1 rounded"
            title="删除会话"
          >
            清空对话
          </button>
        </div>
      )}
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
              <p>{m.content}</p>
              {/* 音频播放按钮 */}
              {m.audioLoading && (
                <div className="mt-2 flex items-center gap-2 text-xs text-white/30">
                  <div className="w-3 h-3 rounded-full border border-white/20 border-t-white/50 animate-spin" />
                  语音合成中...
                </div>
              )}
              {m.audioUrl && (
                <button
                  onClick={() => handlePlayAudio(m.audioUrl!)}
                  className="mt-2 inline-flex items-center gap-1.5 text-xs text-white/50 hover:text-white/80 transition-colors bg-white/5 hover:bg-white/10 rounded-full px-3 py-1"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="5,3 19,12 5,21" />
                  </svg>
                  播放语音
                </button>
              )}
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
