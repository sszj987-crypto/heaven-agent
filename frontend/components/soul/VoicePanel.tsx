"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchVoiceInstallation, fetchVoiceStatus, fetchVoicePreview, installVoice,
  markOnboardingStep, uploadVoiceSample, type VoiceInstallationStatus, type VoiceStatus,
} from "@/lib/api";
import { voiceInstallPresentation } from "./voice-install-state";
import { loadVoicePanelStatus, pollVoiceCreation, voiceProviderPresentation } from "./voice-provider-state";
import { cloudAudioFileError, createVoiceRecording, createVoicePreview } from "./voice-audio";

export default function VoicePanel() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [installation, setInstallation] = useState<VoiceInstallationStatus | null>(null);
  const [recording, setRecording] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState("");
  const lifecycle = useRef(0);
  const recorderRef = useRef<ReturnType<typeof createVoiceRecording> | null>(null);
  const previewRef = useRef<ReturnType<typeof createVoicePreview> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const current = lifecycle.current;
    try {
      const result = await loadVoicePanelStatus(fetchVoiceStatus, fetchVoiceInstallation);
      if (current !== lifecycle.current) return;
      setStatus(result.status); setInstallation(result.installation); setLoadError("");
      localStorage.setItem("voice_ready", String(result.status.has_reference));
    } catch (error) {
      if (current === lifecycle.current) setLoadError(error instanceof Error ? error.message : "无法读取声音状态");
    }
  }, []);

  useEffect(() => {
    const current = lifecycle.current;
    void Promise.resolve().then(() => { if (current === lifecycle.current) void load(); });
    return () => {
      lifecycle.current = current + 1;
      recorderRef.current?.dispose(); previewRef.current?.dispose();
    };
  }, [load]);

  useEffect(() => {
    if (status?.provider !== "local" || installation?.state !== "installing") return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await fetchVoiceInstallation();
        if (cancelled) return;
        setInstallation(next);
        if (next.state === "installed") void load();
      } catch (error) {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : "无法读取安装进度");
      }
    }, 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [status?.provider, installation?.state, load]);

  useEffect(() => {
    if (status?.provider !== "minimax" || status.state !== "creating") return;
    return pollVoiceCreation({
      fetchStatus: fetchVoiceStatus,
      onStatus: next => {
        setStatus(next); setLoadError("");
        localStorage.setItem("voice_ready", String(next.has_reference));
        if (next.provider === "local") void load();
      },
      onError: error => setLoadError(error.message),
    });
  }, [status?.provider, status?.state, load]);

  const startInstall = async () => {
    const current = lifecycle.current;
    setInstalling(true); setLoadError("");
    try { await installVoice(); if (current === lifecycle.current) await load(); }
    catch (error) {
      if (current === lifecycle.current) setLoadError(error instanceof Error ? error.message : "语音组件安装失败");
    } finally { if (current === lifecycle.current) setInstalling(false); }
  };

  const submit = async (blob: Blob) => {
    const current = lifecycle.current;
    setProcessing(false); setUploading(true); setMessage("");
    previewRef.current?.dispose(); setPreviewBusy(false);
    try {
      const result = await uploadVoiceSample(blob);
      if (current !== lifecycle.current) return;
      localStorage.setItem("voice_ready", "true");
      setStatus(previous => previous ? {
        ...previous, has_reference: true, state: "ready", message: "音色已就绪",
        preview_available: previous.provider === "minimax" && result.preview_available,
      } : previous);
      setMessage("音色创建成功，后端已保存");
      await load();
      if (current === lifecycle.current) {
        // Progress-marker failure must not misreport an already-created voice as failed.
        await markOnboardingStep("voice").catch(() => undefined);
      }
    } catch (error) {
      if (current === lifecycle.current) setMessage(error instanceof Error ? error.message : "音色上传失败");
    } finally { if (current === lifecycle.current) setUploading(false); }
  };

  const startRecording = async () => {
    setMessage(""); setPreparing(true);
    recorderRef.current?.dispose();
    recorderRef.current = createVoiceRecording({
      cloud: status?.provider === "minimax",
      stopPlayback: () => { previewRef.current?.dispose(); setPreviewBusy(false); },
      onRecording: active => { setPreparing(false); setRecording(active); setProcessing(!active); },
      onSample: blob => { void submit(blob); },
      onError: error => { setPreparing(false); setRecording(false); setProcessing(false); setMessage(`录音失败：${error.message}`); },
    });
    await recorderRef.current.start();
  };

  const uploadFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const error = status?.provider === "minimax" ? cloudAudioFileError(file) : null;
    if (error) { setMessage(error); return; }
    await submit(file);
  };

  const playPreview = () => {
    setMessage(""); previewRef.current?.dispose();
    previewRef.current = createVoicePreview({ fetch: fetchVoicePreview, onError: error => setMessage(error.message), onBusy: setPreviewBusy });
    void previewRef.current.play();
  };

  const localInstallation = status?.provider === "local" ? installation : null;
  const installView = localInstallation ? voiceInstallPresentation(localInstallation.state) : null;
  const currentStatus = status && localInstallation && localInstallation.state !== "installed"
    ? { ...status, state: localInstallation.state, message: localInstallation.message }
    : status;
  const view = currentStatus ? voiceProviderPresentation(currentStatus) : null;
  const busy = uploading || preparing || processing;

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center px-6 py-3 border-b border-white/10">
        <h3 className="text-sm text-white/50">语音音色</h3>
      </div>
      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        <div role="status" className={`rounded-xl border p-4 flex items-center gap-3 ${view?.ready ? "border-green-500/30 bg-green-500/5" : "border-white/10 bg-white/5"}`}>
          <div className={`w-3 h-3 shrink-0 rounded-full ${view?.ready ? "bg-green-400" : installView?.installing ? "bg-amber-300 animate-pulse" : "bg-white/20"}`} />
          <span className="min-w-0 flex-1 text-sm">{loadError || currentStatus?.message || "正在读取声音状态..."}</span>
          {view?.showInstaller && installView?.canInstall && (
            <button type="button" onClick={startInstall} disabled={installing} className="shrink-0 px-3 py-1.5 text-xs rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-40">
              {installation?.state === "failed" ? "重试安装" : "安装语音组件"}
            </button>
          )}
          {loadError && <button type="button" onClick={() => void load()} className="text-xs text-white/60">重新读取</button>}
        </div>
        {view?.showUpload && (
          <>
            <p className="text-sm text-white/40 leading-relaxed">上传或录制 10–30 秒清晰语音样本。声音克隆属于 AI 模拟，可能与本人存在差异。</p>
            {!status?.supports_instruction && (
              <p className="rounded-xl border border-amber-200/10 bg-amber-100/5 px-4 py-3 text-xs leading-5 text-amber-100/55">当前语音后端支持音色克隆，但不支持逐轮语气指令；文字内容不受影响。</p>
            )}
            {status?.provider === "minimax" && (
              <div className="space-y-2 text-xs leading-5 text-white/50">
                <p>文件支持 WAV、MP3、M4A；浏览器录音会转换为单声道 WAV。</p>
                <p>录音将发送到 MiniMax 创建云端复刻音色；创建后会生成一条短试听完成验证和激活，可能产生服务商费用。</p>
              </div>
            )}
            <div className="flex flex-wrap gap-3 items-center">
              {!recording ? (
                <button type="button" onClick={startRecording} disabled={busy} className="px-4 py-2 text-sm rounded-lg bg-red-500/20 border border-red-500/30 hover:bg-red-500/30 disabled:opacity-40">
                  {preparing ? "正在请求麦克风..." : "录制声音"}
                </button>
              ) : (
                <button type="button" onClick={() => recorderRef.current?.stop()} className="px-4 py-2 text-sm rounded-lg bg-red-500/40 border border-red-500/50 animate-pulse">停止录制</button>
              )}
              <span className="text-xs text-white/20">或</span>
              <button type="button" onClick={() => inputRef.current?.click()} disabled={busy || recording} className="px-4 py-2 text-sm rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-40">上传音频文件</button>
              <input ref={inputRef} type="file" accept={status?.provider === "minimax" ? ".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4" : "audio/*"} onChange={uploadFile} className="hidden" />
              {view.showPreview && <button type="button" onClick={playPreview} disabled={busy || recording || previewBusy} className="px-4 py-2 text-sm rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-40">{previewBusy ? "正在播放试听..." : "播放试听"}</button>}
            </div>
            {processing && <p className="text-xs text-white/30">正在处理录音...</p>}
            {uploading && <p className="text-xs text-white/30">正在上传并创建音色...</p>}
          </>
        )}
        {message && <p role="status" className={`text-xs ${message.includes("成功") ? "text-green-400" : "text-red-400"}`}>{message}</p>}
        {!view?.showUpload && <p className="text-xs text-white/30">文字对话不受影响。</p>}
      </div>
    </div>
  );
}
