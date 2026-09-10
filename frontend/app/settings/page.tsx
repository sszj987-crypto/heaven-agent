"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchSettings, resetDemo, updateSettings, testLLMConnection, type Settings } from "@/lib/api";
import { TTSSettingsSection } from "@/components/settings/TTSSettingsSection";

type LLMProvider = "cloud" | "local";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [llmForm, setLLMForm] = useState({ provider: "cloud" as LLMProvider, cloud: { base_url: "", model: "", temperature: 0.7, api_key: "" }, ollama: { base_url: "http://127.0.0.1:11434/v1", model: "", temperature: 0.7 } });
  const [llmKeyDirty, setLlmKeyDirty] = useState(false);
  const [logLevel, setLogLevel] = useState("error");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [msg, setMsg] = useState("");
  const [llmMsg, setLLMMsg] = useState("");

  const load = useCallback(async () => {
    const s = await fetchSettings();
    setSettings(s);
    setLLMForm({ provider: s.llm.provider, cloud: { ...s.llm.cloud, temperature: s.llm.cloud.temperature ?? 0.7, api_key: "" }, ollama: { ...s.llm.ollama, temperature: s.llm.ollama.temperature ?? 0.7 } });
    setLlmKeyDirty(false);
    setLogLevel(s.log_level || "error");
  }, []);

  useEffect(() => { void load().catch(() => setMsg("无法加载配置，请确认后端服务已启动")); }, [load]);

  const selected = llmForm.provider === "local" ? llmForm.ollama : llmForm.cloud;
  const updateSelected = (key: "base_url" | "model" | "temperature", value: string | number) => {
    setLLMForm((current) => current.provider === "local" ? { ...current, ollama: { ...current.ollama, [key]: value } } : { ...current, cloud: { ...current.cloud, [key]: value } });
    setTestResult(null);
  };

  const handleSaveLLM = useCallback(async () => {
    setSaving(true); setLLMMsg("");
    try {
      const llm = llmForm.provider === "local"
        ? { provider: "local" as const, ollama: llmForm.ollama }
        : { provider: "cloud" as const, cloud: { base_url: llmForm.cloud.base_url, model: llmForm.cloud.model, temperature: llmForm.cloud.temperature, ...(llmKeyDirty ? { api_key: llmForm.cloud.api_key } : {}) } };
      await updateSettings({ llm });
      await load();
      setLLMMsg("对话模型配置已保存");
    } catch (error) {
      setLLMMsg(error instanceof Error ? error.message : "对话模型配置保存失败");
    } finally { setSaving(false); }
  }, [llmForm, llmKeyDirty, load]);

  const handleLogLevelChange = useCallback(async (level: string) => {
    setLogLevel(level);
    try { await updateSettings({ log_level: level }); setMsg("日志等级已切换到 " + level); }
    catch { setMsg("日志等级保存失败"); setLogLevel(level === "debug" ? "error" : "debug"); }
  }, []);

  const handleTest = useCallback(async () => {
    setTesting(true); setTestResult(null);
    try { setTestResult(await testLLMConnection()); } finally { setTesting(false); }
  }, []);

  const handleResetDemo = useCallback(async () => {
    if (!confirm("这会把当前人物档案、声音和对话移入本地备份，并恢复脱敏演示档案。确定继续吗？")) return;
    setResetting(true); setMsg("");
    try { const backup = await resetDemo(); setMsg(`演示数据已恢复；原数据备份于 ${backup}`); }
    catch (error) { setMsg(error instanceof Error ? error.message : "重置失败"); }
    finally { setResetting(false); }
  }, []);

  if (!settings) return <div className="flex items-center justify-center flex-1 text-white/30">加载中...</div>;

  return <div className="desktop-page space-y-8">
    <header className="space-y-2"><h1 className="text-2xl font-light tracking-wide">设置</h1><p className="text-sm text-stone-400">分别配置文字对话与语音服务。</p></header>
    <div className="settings-grid">
      <section aria-labelledby="dialogue-settings-title" className="settings-panel space-y-5">
        <header className="space-y-2"><h2 id="dialogue-settings-title" className="text-lg font-medium text-stone-200">对话模型</h2><p className="text-sm leading-6 text-stone-400">根据人物档案和对话内容生成文字回复。</p></header>
        <div className="flex gap-3">{(["local", "cloud"] as const).map((provider) => <button key={provider} onClick={() => { setLLMForm((f) => ({ ...f, provider })); setTestResult(null); setLLMMsg(""); }} disabled={saving} aria-pressed={llmForm.provider === provider} className={`px-4 py-2 text-sm rounded-lg border transition-colors ${llmForm.provider === provider ? "bg-white/20 border-white/30 text-white" : "bg-white/5 border-white/10 text-white/40 hover:border-white/20 hover:text-white/60"}`}>{provider === "local" ? "本地" : "云端"}</button>)}</div>
        {llmForm.provider === "cloud" && <label className="block"><span className="text-sm text-stone-300">云端渠道</span><select value="openai_compatible" disabled className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none"><option value="openai_compatible">OpenAI 兼容</option></select></label>}
        <p className="text-sm leading-6 text-stone-400">{llmForm.provider === "local" ? "使用本机运行的 Ollama。请先启动 Ollama 并拉取所需模型。" : "使用任意 OpenAI 兼容的云端对话服务。"}</p>
        <label className="block"><span className="text-sm text-stone-300">回复随机性 · {selected.temperature.toFixed(1)}</span><input type="range" min="0" max="2" step="0.1" value={selected.temperature} disabled={saving} onChange={(e) => updateSelected("temperature", Number(e.target.value))} className="w-full mt-2 accent-amber-300/70" /><span className="block text-xs leading-5 text-stone-400">数值越高，表达变化通常越大。</span></label>
        <label className="block"><span className="text-sm text-stone-300">对话模型名称</span><input value={selected.model} disabled={saving} onChange={(e) => updateSelected("model", e.target.value)} className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30" /></label>
        {llmForm.provider === "cloud" && <label className="block"><span className="text-sm text-stone-300">对话服务密钥 <span className="text-xs text-stone-400">· {settings.llm.cloud.api_key_configured ? "已配置，留空保持不变" : "尚未配置"}</span></span><input type="password" value={llmForm.cloud.api_key} disabled={saving} onChange={(e) => { setLlmKeyDirty(true); setLLMForm((f) => ({ ...f, cloud: { ...f.cloud, api_key: e.target.value } })); setTestResult(null); }} className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30" /></label>}
        <details className="rounded-lg border border-white/10 px-4 py-3"><summary className="cursor-pointer text-sm text-stone-300 hover:text-stone-100">高级配置</summary><label className="block mt-4"><span className="text-sm text-stone-300">接口地址</span><input value={selected.base_url} disabled={saving} onChange={(e) => updateSelected("base_url", e.target.value)} className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30" /></label></details>
        <p className="text-xs leading-5 text-stone-400">连接测试使用已保存的当前对话配置，修改后请先保存。</p>
        <div className="flex flex-wrap gap-3"><button onClick={handleSaveLLM} disabled={saving} className="px-4 py-2 text-sm rounded-lg bg-white/10 hover:bg-white/20 transition-colors disabled:opacity-30">{saving ? "保存中..." : "保存对话配置"}</button><button onClick={handleTest} disabled={testing || saving} className="px-4 py-2 text-sm rounded-lg border border-white/20 hover:border-white/40 transition-colors disabled:opacity-30">{testing ? "测试中..." : "测试对话连接"}</button>{testResult !== null && <span role="status" className={`text-sm self-center ${testResult ? "text-green-400" : "text-red-400"}`}>{testResult ? "已保存的对话配置连接成功" : "已保存的对话配置连接失败"}</span>}</div>
        {llmMsg && <p role="status" className="text-sm text-stone-300">{llmMsg}</p>}
      </section>
      <TTSSettingsSection tts={settings.tts} onSaved={load} />
    </div>
    <div className="settings-grid border-t border-amber-100/10 pt-8">
      <section className="space-y-4"><h2 className="text-base font-medium text-stone-300">日志记录</h2><p className="text-sm leading-6 text-stone-400">日常使用保留“仅错误”即可；排查问题时可切换为“详细”。</p><div className="flex gap-3">{(["error", "debug"] as const).map((level) => <button key={level} onClick={() => handleLogLevelChange(level)} aria-pressed={logLevel === level} className={`px-4 py-2 text-sm rounded-lg border transition-colors ${logLevel === level ? "bg-white/20 border-white/30 text-white" : "bg-white/5 border border-white/10 text-white/40 hover:border-white/20 hover:text-white/60"}`}>{level === "debug" ? "详细" : "仅错误"}{logLevel === level && <span className="ml-2 text-green-400">✓</span>}</button>)}</div></section>
      <section className="space-y-4"><h2 className="text-base font-medium text-stone-300">本地数据</h2><p className="text-sm text-stone-400 leading-6">恢复脱敏演示档案。当前人物资料、声音、对话、候选事实和引导状态会先移入可恢复备份；对话模型设置不会改变。</p><button onClick={handleResetDemo} disabled={resetting} className="px-4 py-2 text-sm rounded-lg border border-red-400/20 text-red-200/60 hover:bg-red-400/10 disabled:opacity-30">{resetting ? "正在备份并重置..." : "恢复演示数据"}</button></section>
    </div>
    {msg && <p role="status" className="text-sm text-stone-300">{msg}</p>}
  </div>;
}
