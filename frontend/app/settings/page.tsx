"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchSettings, resetDemo, updateSettings, testLLMConnection, type Settings } from "@/lib/api";
import { TTSSettingsSection } from "@/components/settings/TTSSettingsSection";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [llmForm, setLLMForm] = useState({ base_url: "", model: "", temperature: 0.7, api_key: "" });
  const [logLevel, setLogLevel] = useState("error");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [msg, setMsg] = useState("");
  const [llmMsg, setLLMMsg] = useState("");

  useEffect(() => {
    fetchSettings()
      .then((s) => {
        setSettings(s);
        setLLMForm({
          base_url: s.llm.base_url,
          model: s.llm.model,
          temperature: s.llm.temperature ?? 0.7,
          api_key: "",
        });
        setLogLevel(s.log_level || "error");
      })
      .catch(() => {
        setMsg("无法加载配置，请确认后端服务已启动");
        setSettings({
          llm: { base_url: "", model: "", temperature: 0.7, api_key_configured: false },
          tts: {
            provider: "local",
            minimax: { base_url: "https://api.minimaxi.com", model: "speech-2.8-hd", api_key_configured: false },
          },
          log_level: "error",
        });
      });
  }, []);

  const handleSaveLLM = useCallback(async () => {
    setSaving(true);
    setLLMMsg("");
    try {
      const llm: { base_url: string; model: string; temperature: number; api_key?: string } = {
        base_url: llmForm.base_url,
        model: llmForm.model,
        temperature: llmForm.temperature,
      };
      if (llmForm.api_key) llm.api_key = llmForm.api_key;
      await updateSettings({ llm });
      setLLMMsg("对话模型配置已保存");
    } catch {
      setLLMMsg("对话模型配置保存失败");
    } finally {
      setSaving(false);
    }
  }, [llmForm]);

  const handleLogLevelChange = useCallback(async (level: string) => {
    setLogLevel(level);
    try {
      await updateSettings({ log_level: level });
      setMsg("日志等级已切换到 " + level);
    } catch {
      setMsg("日志等级保存失败");
      setLogLevel(level === "debug" ? "error" : "debug"); // 回滚
    }
  }, []);

  const handleTest = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    const ok = await testLLMConnection();
    setTestResult(ok);
    setTesting(false);
  }, []);

  const refreshTTSSettings = useCallback(async () => {
    const refreshed = await fetchSettings();
    setSettings(refreshed);
  }, []);

  const handleResetDemo = useCallback(async () => {
    if (!confirm("这会把当前人物档案、声音和对话移入本地备份，并恢复脱敏演示档案。确定继续吗？")) {
      return;
    }
    setResetting(true);
    setMsg("");
    try {
      const backup = await resetDemo();
      setMsg(`演示数据已恢复；原数据备份于 ${backup}`);
    } catch (error) {
      setMsg(error instanceof Error ? error.message : "重置失败");
    } finally {
      setResetting(false);
    }
  }, []);

  if (!settings) {
    return <div className="flex items-center justify-center flex-1 text-white/30">加载中...</div>;
  }

  return (
    <div className="desktop-page space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-light tracking-wide">设置</h1>
        <p className="text-sm text-stone-400">分别配置文字对话与语音服务。</p>
      </header>

      <div className="settings-grid">
      {/* LLM 配置 */}
      <section aria-labelledby="dialogue-settings-title" className="settings-panel space-y-5">
        <header className="space-y-2">
          <h2 id="dialogue-settings-title" className="text-lg font-medium text-stone-200">对话模型</h2>
          <p className="text-sm leading-6 text-stone-400">根据人物档案和对话内容生成文字回复。</p>
        </header>

        <label className="block">
          <span className="text-sm text-stone-300">接口地址</span>
          <input
            value={llmForm.base_url}
            onChange={(e) => setLLMForm((f) => ({ ...f, base_url: e.target.value }))}
            className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30"
          />
        </label>

        <label className="block">
          <span className="text-sm text-stone-300">回复随机性 · {llmForm.temperature.toFixed(1)}</span>
          <input
            type="range"
            min="0"
            max="2"
            step="0.1"
            value={llmForm.temperature}
            onChange={(e) => setLLMForm((f) => ({ ...f, temperature: Number(e.target.value) }))}
            className="w-full mt-2 accent-amber-300/70"
            aria-describedby="temperature-help"
          />
          <span id="temperature-help" className="block text-xs leading-5 text-stone-400">数值越高，表达变化通常越大。</span>
        </label>

        <label className="block">
          <span className="text-sm text-stone-300">对话模型名称</span>
          <input
            value={llmForm.model}
            onChange={(e) => setLLMForm((f) => ({ ...f, model: e.target.value }))}
            className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30"
          />
        </label>

        <label className="block">
          <span className="text-sm text-stone-300">
            对话服务密钥 <span className="text-xs text-stone-400">· {settings.llm.api_key_configured ? "已配置，留空保持不变" : "尚未配置"}</span>
          </span>
          <input
            type="password"
            value={llmForm.api_key}
            onChange={(e) => setLLMForm((f) => ({ ...f, api_key: e.target.value }))}
            className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30"
          />
        </label>

        <p className="text-xs leading-5 text-stone-400">连接测试使用已保存的对话配置，修改后请先保存。</p>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={handleSaveLLM}
            disabled={saving}
            className="px-4 py-2 text-sm rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
          >
            {saving ? "保存中..." : "保存对话配置"}
          </button>
          <button
            onClick={handleTest}
            disabled={testing}
            className="px-4 py-2 text-sm rounded-lg border border-white/20 hover:border-white/40 transition-colors"
          >
            {testing ? "测试中..." : "测试对话连接"}
          </button>
          {testResult !== null && (
            <span role="status" className={`text-sm self-center ${testResult ? "text-green-400" : "text-red-400"}`}>
              {testResult ? "已保存的对话配置连接成功" : "已保存的对话配置连接失败"}
            </span>
          )}
        </div>
        {llmMsg && <p role="status" className="text-sm text-stone-300">{llmMsg}</p>}
      </section>

      <TTSSettingsSection tts={settings.tts} onSaved={refreshTTSSettings} />
      </div>

      <div className="settings-grid border-t border-amber-100/10 pt-8">
      {/* 日志等级 */}
      <section className="space-y-4">
        <h2 className="text-base font-medium text-stone-300">日志记录</h2>
        <p className="text-sm leading-6 text-stone-400">日常使用保留“仅错误”即可；排查问题时可切换为“详细”。</p>

        <div className="flex gap-3">
          {(["error", "debug"] as const).map((level) => (
            <button
              key={level}
              onClick={() => handleLogLevelChange(level)}
              aria-pressed={logLevel === level}
              className={`px-4 py-2 text-sm rounded-lg border transition-colors ${
                logLevel === level
                  ? "bg-white/20 border-white/30 text-white"
                  : "bg-white/5 border-white/10 text-white/40 hover:border-white/20 hover:text-white/60"
              }`}
            >
              {level === "debug" ? "详细" : "仅错误"}
              {logLevel === level && <span className="ml-2 text-green-400">✓</span>}
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-base font-medium text-stone-300">本地数据</h2>
        <p className="text-sm text-stone-400 leading-6">
          恢复脱敏演示档案。当前人物资料、声音、对话、候选事实和引导状态会先移入可恢复备份；对话模型设置不会改变。
        </p>
        <button
          onClick={handleResetDemo}
          disabled={resetting}
          className="px-4 py-2 text-sm rounded-lg border border-red-400/20 text-red-200/60 hover:bg-red-400/10 disabled:opacity-30"
        >
          {resetting ? "正在备份并重置..." : "恢复演示数据"}
        </button>
      </section>
      </div>

      {msg && <p role="status" className="text-sm text-stone-300">{msg}</p>}
    </div>
  );
}
