"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchSettings, updateSettings, testLLMConnection, type Settings } from "@/lib/api";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [llmForm, setLLMForm] = useState({ base_url: "", model: "", api_key: "" });
  const [voiceUrl, setVoiceUrl] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    fetchSettings()
      .then((s) => {
        setSettings(s);
        setLLMForm({ base_url: s.llm.base_url, model: s.llm.model, api_key: s.llm.api_key });
        setVoiceUrl(s.voice.fish_speech_url);
      })
      .catch(() => setMsg("无法加载配置"));
  }, []);

  const handleSaveLLM = useCallback(async () => {
    setSaving(true);
    setMsg("");
    try {
      await updateSettings({
        llm: { base_url: llmForm.base_url, model: llmForm.model, api_key: llmForm.api_key },
      });
      setMsg("LLM 配置已保存");
    } catch {
      setMsg("保存失败");
    } finally {
      setSaving(false);
    }
  }, [llmForm]);

  const handleSaveVoice = useCallback(async () => {
    setSaving(true);
    setMsg("");
    try {
      await updateSettings({ voice: { fish_speech_url: voiceUrl } });
      setMsg("语音配置已保存");
    } catch {
      setMsg("保存失败");
    } finally {
      setSaving(false);
    }
  }, [voiceUrl]);

  const handleTest = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    const ok = await testLLMConnection();
    setTestResult(ok);
    setTesting(false);
  }, []);

  if (!settings) {
    return <div className="flex items-center justify-center flex-1 text-white/30">加载中...</div>;
  }

  return (
    <div className="max-w-xl mx-auto px-6 py-10 space-y-10">
      <h2 className="text-xl font-light tracking-wide">设置</h2>

      {/* LLM 配置 */}
      <section className="space-y-4">
        <h3 className="text-sm text-white/50 uppercase tracking-wider">LLM</h3>

        <label className="block">
          <span className="text-xs text-white/30">Base URL</span>
          <input
            value={llmForm.base_url}
            onChange={(e) => setLLMForm((f) => ({ ...f, base_url: e.target.value }))}
            className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30"
          />
        </label>

        <label className="block">
          <span className="text-xs text-white/30">Model</span>
          <input
            value={llmForm.model}
            onChange={(e) => setLLMForm((f) => ({ ...f, model: e.target.value }))}
            className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30"
          />
        </label>

        <label className="block">
          <span className="text-xs text-white/30">API Key</span>
          <input
            type="password"
            value={llmForm.api_key}
            onChange={(e) => setLLMForm((f) => ({ ...f, api_key: e.target.value }))}
            className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30"
          />
        </label>

        <div className="flex gap-3">
          <button
            onClick={handleSaveLLM}
            disabled={saving}
            className="px-4 py-2 text-sm rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
          >
            保存 LLM 配置
          </button>
          <button
            onClick={handleTest}
            disabled={testing}
            className="px-4 py-2 text-sm rounded-lg border border-white/20 hover:border-white/40 transition-colors"
          >
            {testing ? "测试中..." : "测试连接"}
          </button>
          {testResult !== null && (
            <span className={`text-sm self-center ${testResult ? "text-green-400" : "text-red-400"}`}>
              {testResult ? "连接成功" : "连接失败"}
            </span>
          )}
        </div>
      </section>

      {/* Voice 配置 */}
      <section className="space-y-4">
        <h3 className="text-sm text-white/50 uppercase tracking-wider">语音 (Fish Speech)</h3>

        <label className="block">
          <span className="text-xs text-white/30">Fish Speech URL</span>
          <input
            value={voiceUrl}
            onChange={(e) => setVoiceUrl(e.target.value)}
            className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30"
          />
        </label>

        <button
          onClick={handleSaveVoice}
          disabled={saving}
          className="px-4 py-2 text-sm rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
        >
          保存语音配置
        </button>
      </section>

      {msg && <p className="text-sm text-white/40">{msg}</p>}

      {/* Circumstances */}
      {settings.circumstances && (
        <section className="space-y-2">
          <h3 className="text-sm text-white/50 uppercase tracking-wider">当前场景</h3>
          <pre className="text-sm text-white/30 whitespace-pre-wrap bg-white/5 rounded-lg p-3 border border-white/5">
            {settings.circumstances}
          </pre>
        </section>
      )}
    </div>
  );
}
