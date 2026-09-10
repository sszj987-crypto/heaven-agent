"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchVoiceStatus, fetchVoicePreview, localReferenceCandidateAudioUrl, markOnboardingStep,
  prepareLocalReferenceCandidates, selectLocalReferenceCandidate, uploadVoiceSample,
  type LocalReferenceCandidate, type VoiceStatus,
} from "@/lib/api";
import { pollVoiceCreation, voiceProviderPresentation } from "./voice-provider-state";
import { cloudAudioFileError, createVoiceRecording, createVoicePreview } from "./voice-audio";

export default function VoicePanel() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [recording, setRecording] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [referenceCandidates, setReferenceCandidates] = useState<LocalReferenceCandidate[]>([]);
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
      const result = await fetchVoiceStatus();
      if (current !== lifecycle.current) return;
      setStatus(result); setLoadError("");
      localStorage.setItem("voice_ready", String(result.ready));
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
    if (status?.provider !== "minimax" || status.state !== "creating") return;
    return pollVoiceCreation({
      fetchStatus: fetchVoiceStatus,
      onStatus: next => {
        setStatus(next); setLoadError("");
        localStorage.setItem("voice_ready", String(next.ready));
        if (next.provider === "local") void load();
      },
      onError: error => setLoadError(error.message),
    });
  }, [status?.provider, status?.state, load]);

  const activateReference = async (result: { preview_available: boolean }, successMessage: string) => {
    const current = lifecycle.current;
    localStorage.setItem("voice_ready", "true");
    setStatus(previous => previous ? {
      ...previous, has_reference: true, ready: true, state: "ready", message: "音色已就绪",
      preview_available: previous.provider === "minimax" && result.preview_available,
    } : previous);
    setMessage(successMessage);
    await load();
    if (current === lifecycle.current) {
      // Progress-marker failure must not misreport an already-created voice as failed.
      await markOnboardingStep("voice").catch(() => undefined);
    }
  };

  const submit = async (blob: Blob) => {
    const current = lifecycle.current;
    setProcessing(false); setUploading(true); setMessage(""); setReferenceCandidates([]);
    previewRef.current?.dispose(); setPreviewBusy(false);
    try {
      if (status?.provider === "local") {
        const candidates = await prepareLocalReferenceCandidates(blob);
        if (current === lifecycle.current) {
          setReferenceCandidates(candidates);
          setMessage("请试听并选择最像 TA 平时说话的一段。");
        }
        return;
      }
      await activateReference(await uploadVoiceSample(blob), "音色创建成功，后端已保存");
    } catch (error) {
      if (current === lifecycle.current) setMessage(error instanceof Error ? error.message : "音色上传失败");
    } finally { if (current === lifecycle.current) setUploading(false); }
  };

  const selectCandidate = async (candidateId: string) => {
    const current = lifecycle.current;
    setUploading(true); setMessage("");
    try {
      await activateReference(await selectLocalReferenceCandidate(candidateId), "参考片段保存成功，已成为当前音色样本");
      if (current === lifecycle.current) setReferenceCandidates([]);
    } catch (error) {
      if (current === lifecycle.current) setMessage(error instanceof Error ? error.message : "保存参考片段失败");
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

  const view = status ? voiceProviderPresentation(status) : null;
  const busy = uploading || preparing || processing;

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center px-6 py-3 border-b border-white/10">
        <h3 className="text-sm text-white/50">语音音色</h3>
      </div>
      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        <div role="status" className={`rounded-xl border p-4 flex items-center gap-3 ${view?.ready ? "border-green-500/30 bg-green-500/5" : "border-white/10 bg-white/5"}`}>
          <div className={`w-3 h-3 shrink-0 rounded-full ${view?.ready ? "bg-green-400" : "bg-white/20"}`} />
          <span className="min-w-0 flex-1 text-sm">{loadError || status?.message || "正在读取声音状态..."}</span>
          {loadError && <button type="button" onClick={() => void load()} className="text-xs text-white/60">重新读取</button>}
        </div>
        {view?.showUpload && (
          <>
            <p className="text-sm text-white/40 leading-relaxed">{status?.provider === "local" ? "上传或录制清晰语音后，试听并选择一段最像 TA 日常说话的 10 秒片段。" : "上传或录制 10–30 秒清晰语音样本。"} 声音克隆属于 AI 模拟，可能与本人存在差异。</p>
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
            {status?.provider === "local" && referenceCandidates.length > 0 && (
              <div className="space-y-3 rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-xs leading-5 text-white/50">系统优先挑出声音较明显的片段；请以“最像 TA 平时说话”为准选择。选定后才会替换当前参考音。</p>
                <div className="grid gap-3 sm:grid-cols-3">
                  {referenceCandidates.map(candidate => (
                    <div key={candidate.id} className="space-y-2 rounded-lg border border-white/10 p-3">
                      <p className="text-xs text-white/70">{candidate.label} · {candidate.duration_seconds} 秒</p>
                      <audio controls preload="none" className="w-full" src={localReferenceCandidateAudioUrl(candidate.id)} />
                      <button type="button" onClick={() => void selectCandidate(candidate.id)} disabled={busy} className="w-full rounded-lg bg-white/10 px-3 py-2 text-xs hover:bg-white/20 disabled:opacity-40">选择这段</button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
        {status?.provider === "openai_compatible" && (
          <p className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-xs leading-5 text-white/50">
            当前 OpenAI 兼容语音服务使用设置页配置的 voice 名称或 ID 合成，不支持在应用内上传录音、创建自定义音色或生成音色试听。
          </p>
        )}
        {message && <p role="status" className={`text-xs ${message.includes("成功") ? "text-green-400" : message.startsWith("请试听") ? "text-white/50" : "text-red-400"}`}>{message}</p>}
        {status?.provider === "local" && status.state === "not_installed" && (
          <p className="text-xs leading-5 text-white/40">本地语音组件尚未安装，请前往“设置 → 语音服务 → 本地”安装。文字对话不受影响。</p>
        )}
        {!view?.showUpload && status?.state !== "not_installed" && <p className="text-xs text-white/30">文字对话不受影响。</p>}
      </div>
    </div>
  );
}
