"use client";

import { useState } from "react";
import { testTTSConnection, updateSettings, type TTSProvider, type TTSSettings } from "@/lib/api";
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
  return {
    provider: tts.provider,
    base_url: tts.minimax.base_url,
    model: tts.minimax.model,
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
  const formLocked = isTTSFormLocked(saving);

  const invalidateConnection = () => setConnectionStatus(invalidateTTSConnection);

  const setProvider = (provider: TTSProvider) => {
    setForm((current) => ({ ...current, provider }));
    invalidateConnection();
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

  return (
    <section aria-labelledby="speech-settings-title" className="settings-panel space-y-5">
      <header className="space-y-2">
        <h2 id="speech-settings-title" className="text-lg font-medium text-stone-200">语音服务</h2>
        <p className="text-sm leading-6 text-stone-400">将文字回复转换成声音，不影响文字回复的生成。</p>
      </header>
      <div className="flex gap-3">
        {(["local", "minimax"] as const).map((provider) => (
          <button
            key={provider}
            onClick={() => setProvider(provider)}
            aria-pressed={form.provider === provider}
            disabled={formLocked}
            className={`px-4 py-2 text-sm rounded-lg border transition-colors ${
              form.provider === provider
                ? "bg-white/20 border-white/30 text-white"
                : "bg-white/5 border-white/10 text-white/40 hover:border-white/20 hover:text-white/60"
            }`}
          >
            {provider === "local" ? "本地" : "MiniMax"}
          </button>
        ))}
      </div>

      <p className="text-sm leading-6 text-stone-400">
        {form.provider === "local"
          ? "在本机生成语音。语音组件安装和音色管理请前往“灵魂档案 → 语音音色”。"
          : "使用 MiniMax 云端生成语音，无需安装本地语音合成组件。音色管理请前往“灵魂档案 → 语音音色”。"}
      </p>

      {form.provider === "minimax" && (
        <div className="space-y-4">
          <label className="block">
            <span className="text-sm text-stone-300">
              MiniMax 语音密钥 <span className="text-xs text-stone-400">· {tts.minimax.api_key_configured ? "已配置，留空保持不变" : "尚未配置"}</span>
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
          <p id="speech-key-help" className="text-xs leading-5 text-stone-400">仅用于 MiniMax 语音服务，与对话服务密钥分别配置。</p>
          {tts.minimax.api_key_configured && (
            <button
              onClick={() => {
                setKeyDirty(true);
                setForm((current) => ({ ...current, api_key: "" }));
                invalidateConnection();
              }}
              disabled={formLocked}
              className="text-xs text-red-200/60 hover:text-red-200 transition-colors"
            >
              清除 MiniMax 语音密钥
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

      {form.provider === "minimax" && (
        <p className="text-xs leading-5 text-stone-400">连接测试使用已保存的语音配置，不生成音频。修改后请先保存。</p>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          onClick={save}
          disabled={formLocked}
          className="px-4 py-2 text-sm rounded-lg bg-white/10 hover:bg-white/20 transition-colors disabled:opacity-30"
        >
          {saving ? "保存中..." : "保存语音配置"}
        </button>
        {form.provider === "minimax" && (
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
