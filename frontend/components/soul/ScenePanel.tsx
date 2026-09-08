"use client";

import { useEffect, useState } from "react";

import {
  fetchCircumstances,
  updateCircumstances,
  type SceneOption,
} from "@/lib/api";


export default function ScenePanel() {
  const [content, setContent] = useState("");
  const [original, setOriginal] = useState("");
  const [scenes, setScenes] = useState<SceneOption[]>([]);
  const [currentSceneKey, setCurrentSceneKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetchCircumstances()
      .then((data) => {
        setContent(data.content);
        setOriginal(data.content);
        setScenes(data.scenes);
        setCurrentSceneKey(data.scene);
      })
      .catch(() => setMessage("场景加载失败"));
  }, []);

  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      await updateCircumstances(content);
      setOriginal(content);
      setMessage("已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const modified = content !== original;
  const sceneLabel =
    currentSceneKey === "heaven"
      ? "温暖花园（想象场景）"
      : currentSceneKey === "custom"
        ? "自定义"
        : currentSceneKey;

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/10">
        <div className="flex items-center gap-3">
          <h3 className="text-sm text-white/50">人物所在场景</h3>
          <span className="text-xs px-2 py-0.5 rounded bg-white/10 text-white/50">
            {sceneLabel}
          </span>
        </div>
        <button
          onClick={save}
          disabled={!modified || saving}
          className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
            modified
              ? "bg-white/20 text-white hover:bg-white/30"
              : "bg-white/5 text-white/20"
          }`}
        >
          {saving ? "保存中..." : modified ? "保存" : "已保存"}
        </button>
      </div>
      <div className="px-6 py-3 border-b border-white/5">
        <div className="text-xs text-white/30 mb-2">
          选择预设场景，或直接在下方编辑器中自定义
        </div>
        <div className="flex gap-2 flex-wrap">
          {scenes.map((scene) => (
            <button
              key={scene.key}
              onClick={() => {
                setContent(scene.prompt);
                setCurrentSceneKey(scene.key);
              }}
              className={`px-3 py-1.5 text-xs rounded-lg border transition-all ${
                currentSceneKey === scene.key
                  ? "bg-white/10 border-white/30 text-white/80"
                  : "bg-white/5 border-white/10 text-white/40 hover:border-white/20 hover:text-white/60"
              }`}
            >
              {scene.label}
              {currentSceneKey === scene.key && <span className="ml-1.5 text-green-400">✓</span>}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 p-6 pb-0 overflow-y-auto">
        <textarea
          value={content}
          onChange={(event) => {
            setContent(event.target.value);
            setCurrentSceneKey("custom");
          }}
          className="w-full h-full min-h-[300px] bg-transparent text-sm text-white/70 outline-none resize-none font-mono leading-relaxed"
          placeholder="场景描述..."
        />
      </div>
      {message && (
        <div className="px-6 py-2 border-t border-white/5 text-xs text-white/30">
          {message}
        </div>
      )}
    </div>
  );
}
