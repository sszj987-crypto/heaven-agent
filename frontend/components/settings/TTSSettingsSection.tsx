"use client";

import { useEffect, useState } from "react";
import {
  fetchVoiceInstallation, installVoice, testTTSConnection, updateSettings,
  type TTSProvider, type TTSSettings, type VoiceInstallationStatus,
} from "@/lib/api";
import { voiceInstallPresentation } from "./voice-install-state";
import {
  buildTTSUpdate,
  invalidateTTSConnection,
  isTTSFormLocked,
  resetTTSFormAfterSave,
  runTTSConnectionTest,
  type TTSConnectionStatus,
  type TTSSettingsForm,
} from "./tts-settings-state";

function formFromSettings(tts: TTSSettings): TTSSettingsForm {
  const cloud = tts.provider === "openai_compatible" ? tts.openai_compatible : tts.minimax;
  return {
    provider: tts.provider,
    auto_play: tts.auto_play ?? false,
    audio_cache_size: tts.audio_cache_size ?? 10,
    base_url: cloud.base_url,
    model: cloud.model,
    voice: tts.provider === "openai_compatible" ? tts.openai_compatible.voice : "",
    api_key: "",
  };
}

export function TTSSettingsSection({
  tts,
  onSaved,
}: {
  tts: TTSSettings;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState<TTSSettingsForm>(() => formFromSettings(tts));
  const [keyDirty, setKeyDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<TTSConnectionStatus>({ revision: 0, result: null, error: null });
  const [message, setMessage] = useState("");
  const [installation, setInstallation] = useState<VoiceInstallationStatus | null>(null);
  const [installationError, setInstallationError] = useState("");
  const [installing, setInstalling] = useState(false);
  const formLocked = isTTSFormLocked(saving);

  useEffect(() => {
    if (form.provider !== "local") return;
    let cancelled = false;
    void fetchVoiceInstallation()
      .then((status) => {
        if (!cancelled) {
          setInstallation(status);
          setInstallationError("");
        }
      })
      .catch((error) => {
        if (!cancelled) setInstallationError(error instanceof Error ? error.message : "无法读取语音组件状态");
      });
    return () => { cancelled = true; };
  }, [form.provider]);

  useEffect(() => {
    if (form.provider !== "local" || installation?.state !== "installing") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await fetchVoiceInstallation();
        if (!cancelled) {
          setInstallation(status);
          setInstallationError("");
        }
      } catch (error) {
        if (!cancelled) setInstallationError(error instanceof Error ? error.message : "无法读取安装进度");
      }
    };
    const timer = window.setInterval(() => { void poll(); }, 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [form.provider, installation?.state]);

  const invalidateConnection = () => setConnectionStatus(invalidateTTSConnection);

  const setProvider = (provider: TTSProvider) => {
    const cloud = provider === "openai_compatible" ? tts.openai_compatible : tts.minimax;
    setForm((current) => ({
      ...current, provider, base_url: cloud.base_url, model: cloud.model,
      voice: provider === "openai_compatible" ? tts.openai_compatible.voice : "", api_key: "",
    }));
    invalidateConnection();
  };

  const setServiceType = (type: "local" | "cloud") => {
    if (type === "local") {
      setProvider("local");
      return;
    }
    // Restore the saved cloud channel; default to MiniMax for a first switch.
    setProvider(tts.provider === "openai_compatible" ? "openai_compatible" : "minimax");
  };

  const save = async () => {
    setSaving(true);
    setMessage("");
    invalidateConnection();
    try {
      await updateSettings({ tts: buildTTSUpdate(form, keyDirty) });
      const reset = resetTTSFormAfterSave(form);
      setForm(reset.form);
      setKeyDirty(reset.keyDirty);
      await onSaved();
      setMessage("语音配置已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    const revision = connectionStatus.revision;
    setConnectionStatus((status) => ({ ...status, result: null, error: null }));
    setMessage("");
    try {
      await runTTSConnectionTest(revision, testTTSConnection, setConnectionStatus);
    } finally {
      setTesting(false);
    }
  };

  const startInstallation = async () => {
    setInstalling(true);
    setInstallationError("");
    try {
      await installVoice();
      setInstallation(await fetchVoiceInstallation());
    } catch (error) {
      setInstallationError(error instanceof Error ? error.message : "语音组件安装失败");
    } finally {
      setInstalling(false);
    }
  };

  const installView = installation ? voiceInstallPresentation(installation.state) : null;

  return (
    <section aria-labelledby="speech-settings-title" className="settings-panel space-y-5">
      <header className="space-y-2">
        <h2 id="speech-settings-title" className="text-lg font-medium text-stone-200">语音服务</h2>
        <p className="text-sm leading-6 text-stone-400">将文字回复转换成声音，不影响文字回复的生成。</p>
      </header>
      <div className="flex gap-3">
        {(["local", "cloud"] as const).map((type) => (
          <button
            key={type}
            onClick={() => setServiceType(type)}
            aria-pressed={type === "local" ? form.provider === "local" : form.provider !== "local"}
            disabled={formLocked}
            className={`px-4 py-2 text-sm rounded-lg border transition-colors ${
              (type === "local" ? form.provider === "local" : form.provider !== "local")
                ? "bg-white/20 border-white/30 text-white"
                : "bg-white/5 border-white/10 text-white/40 hover:border-white/20 hover:text-white/60"
            }`}
          >
            {type === "local" ? "本地" : "云端"}
          </button>
        ))}
      </div>

      {form.provider !== "local" && (
        <label className="block">
          <span className="text-sm text-stone-300">云端渠道</span>
          <select
            value={form.provider}
            disabled={formLocked}
            onChange={(event) => setProvider(event.target.value as Exclude<TTSProvider, "local">)}
            className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30"
          >
            <option value="minimax">MiniMax</option>
            <option value="openai_compatible">OpenAI 兼容</option>
          </select>
        </label>
      )}

      <p className="text-sm leading-6 text-stone-400">
        {form.provider === "local"
          ? "在本机生成语音。在此安装和更新本地语音组件；录制声音与音色管理请前往“灵魂档案 → 语音音色”。"
          : form.provider === "minimax"
            ? "使用 MiniMax 云端生成语音，无需安装本地语音合成组件。音色管理请前往“灵魂档案 → 语音音色”。"
            : "使用 OpenAI / NewAPI 格式的云端语音接口，无需安装本地语音组件。在这里配置服务商提供的 voice 名称或 ID。"}
      </p>

      {form.provider === "local" && (
        <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4 space-y-3" aria-live="polite">
          <div className="flex items-start gap-3">
            <div className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${installation?.state === "installed" ? "bg-green-400" : installView?.installing ? "bg-amber-300 animate-pulse" : "bg-white/25"}`} />
            <div className="min-w-0 flex-1">
              <h3 className="text-sm text-stone-200">本地语音组件</h3>
              <p className="mt-1 text-xs leading-5 text-stone-400">
                {installationError || installation?.message || "正在读取语音组件状态..."}
              </p>
            </div>
            {installView?.canInstall && (
              <button
                type="button"
                onClick={startInstallation}
                disabled={installing}
                className="shrink-0 px-3 py-1.5 text-xs rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-40"
              >
                {installation?.state === "failed" ? "重试安装" : "安装语音组件"}
              </button>
            )}
          </div>
          {installView?.restartRequired && (
            <p className="text-xs leading-5 text-amber-100/70">重启 Heaven Agent 后，本地语音与音色录制功能即可使用。</p>
          )}
          {installationError && (
            <button type="button" onClick={() => {
              void fetchVoiceInstallation()
                .then((status) => { setInstallation(status); setInstallationError(""); })
                .catch((error) => setInstallationError(error instanceof Error ? error.message : "无法读取语音组件状态"));
            }} className="text-xs text-white/60 hover:text-white">重新读取</button>
          )}
        </div>
      )}

      <label className="flex items-start gap-3 rounded-lg border border-white/10 px-4 py-3">
        <input
          type="checkbox"
          checked={form.auto_play}
          disabled={formLocked}
          onChange={(event) => setForm((current) => ({ ...current, auto_play: event.target.checked }))}
          aria-describedby="speech-autoplay-help"
          className="mt-1 h-4 w-4 accent-stone-200"
        />
        <span>
          <span className="text-sm text-stone-200">自动播放语音</span>
          <span id="speech-autoplay-help" className="mt-1 block text-xs leading-5 text-stone-400">
            默认关闭。开启并保存后，新回复的语音就绪时自动播放。本地语音会提前生成，关闭时可手动播放。
          </span>
        </span>
      </label>

      <label className="block max-w-xs">
        <span className="text-sm text-stone-200">保留语音数量</span>
        <span className="mt-1 block text-xs leading-5 text-stone-400">已播放的语音会在切换页面后保留；设为 0 可关闭缓存。</span>
        <input
          type="number"
          min="0"
          max="100"
          value={form.audio_cache_size}
          disabled={formLocked}
          onChange={(event) => setForm((current) => ({
            ...current,
            audio_cache_size: Math.max(0, Math.min(100, Number(event.target.value) || 0)),
          }))}
          className="w-full mt-2 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30"
        />
      </label>

      {form.provider !== "local" && (
        <div className="space-y-4">
          <label className="block">
            <span className="text-sm text-stone-300">
              {form.provider === "minimax" ? "MiniMax" : "OpenAI 兼容"} 语音密钥 <span className="text-xs text-stone-400">· {(form.provider === "minimax" ? tts.minimax.api_key_configured : tts.openai_compatible.api_key_configured) ? "已配置，留空保持不变" : "尚未配置"}</span>
            </span>
            <input
              type="password"
              aria-describedby="speech-key-help"
              value={form.api_key}
              disabled={formLocked}
              onChange={(event) => {
                setKeyDirty(true);
                setForm((current) => ({ ...current, api_key: event.target.value }));
                invalidateConnection();
              }}
              className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30"
            />
          </label>
          <p id="speech-key-help" className="text-xs leading-5 text-stone-400">仅用于当前语音服务，与对话服务密钥分别配置。</p>
          {(form.provider === "minimax" ? tts.minimax.api_key_configured : tts.openai_compatible.api_key_configured) && (
            <button
              onClick={() => {
                setKeyDirty(true);
                setForm((current) => ({ ...current, api_key: "" }));
                invalidateConnection();
              }}
              disabled={formLocked}
              className="text-xs text-red-200/60 hover:text-red-200 transition-colors"
            >
              清除当前语音密钥
            </button>
          )}
          <details className="rounded-lg border border-white/10 px-4 py-3">
            <summary className="cursor-pointer text-sm text-stone-300 hover:text-stone-100">高级配置</summary>
            <div className="mt-4 space-y-4">
              <p className="text-xs leading-5 text-stone-400">通常无需修改；这里的模型仅用于生成声音。</p>
              <label className="block">
                <span className="text-sm text-stone-300">语音接口地址</span>
                <input
                  value={form.base_url}
                  disabled={formLocked}
                  onChange={(event) => {
                    setForm((current) => ({ ...current, base_url: event.target.value }));
                    invalidateConnection();
                  }}
                  className="w-full bg-white/5 border border-white/10 rounded-lg text-sm outline-none focus:border-white/30"
                />
              </label>
              {form.provider === "openai_compatible" && (
                <label className="block">
                  <span className="text-sm text-stone-300">Voice 名称或 ID</span>
                  <input
                    list="openai-voice-options"
                    value={form.voice}
                    disabled={formLocked}
                    onChange={(event) => { setForm((current) => ({ ...current, voice: event.target.value })); invalidateConnection(); }}
                    className="w-full bg-white/5 border border-white/10 rounded-lg text-sm outline-none focus:border-white/30"
                  />
                  <datalist id="openai-voice-options">
                    {["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse", "marin", "cedar"].map((voice) => <option key={voice} value={voice} />)}
                  </datalist>
                  <span className="mt-1 block text-xs leading-5 text-stone-400">可填写服务商预置 voice，或未来可用的自定义 voice ID。</span>
                </label>
              )}
              <label className="block">
                <span className="text-sm text-stone-300">语音模型名称</span>
                <input
                  value={form.model}
                  disabled={formLocked}
                  onChange={(event) => {
                    setForm((current) => ({ ...current, model: event.target.value }));
                    invalidateConnection();
                  }}
                  className="w-full bg-white/5 border border-white/10 rounded-lg text-sm outline-none focus:border-white/30"
                />
              </label>
            </div>
          </details>
        </div>
      )}

      {form.provider !== "local" && (
        <p className="text-xs leading-5 text-stone-400">连接测试使用已保存的语音配置，不生成音频。OpenAI 兼容服务通过 `/models` 验证网关与鉴权，首次播放才会验证 TTS 模型权限。修改后请先保存。</p>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          onClick={save}
          disabled={formLocked}
          className="px-4 py-2 text-sm rounded-lg bg-white/10 hover:bg-white/20 transition-colors disabled:opacity-30"
        >
          {saving ? "保存中..." : "保存语音配置"}
        </button>
        {form.provider !== "local" && (
          <button
            onClick={testConnection}
            disabled={testing || formLocked}
            className="px-4 py-2 text-sm rounded-lg border border-white/20 hover:border-white/40 transition-colors disabled:opacity-30"
          >
            {testing ? "测试中..." : "测试语音连接"}
          </button>
        )}
        {connectionStatus.result !== null && (
          <span role="status" className={`text-sm self-center ${connectionStatus.result ? "text-green-400" : "text-red-400"}`}>
            {connectionStatus.result ? "已保存的语音配置连接成功" : "已保存的语音配置连接失败"}
          </span>
        )}
      </div>
      {connectionStatus.error && <p role="status" className="text-sm text-red-400">{connectionStatus.error}</p>}
      {message && <p role="status" className="text-sm text-stone-300">{message}</p>}
    </section>
  );
}
