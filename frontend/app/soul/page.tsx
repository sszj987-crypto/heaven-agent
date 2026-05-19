"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchSoul, fetchDimension, updateDimension } from "@/lib/api";

const DIMENSION_LABELS: Record<string, string> = {
  basic_info: "基本信息",
  personality: "性格",
  life_experiences: "人生经历",
  relationships: "人际关系",
  hobbies: "爱好",
  special_habits: "特殊习惯",
  values_beliefs: "价值观与信仰",
  emotional_anchors: "情感锚点",
  linguistic_fingerprint: "语言指纹",
  knowledge_domain: "知识领域",
};

const DIMENSIONS = Object.keys(DIMENSION_LABELS);

export default function SoulPage() {
  const [activeDim, setActiveDim] = useState("basic_info");
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [soulName, setSoulName] = useState("");

  useEffect(() => {
    fetchSoul()
      .then((profile) => {
        const basicInfo = profile.dimensions.basic_info || "";
        const match = basicInfo.match(/name:\s*(.+)/);
        if (match) setSoulName(match[1].trim());
      })
      .catch(() => {});
  }, []);

  const loadDimension = useCallback(async (dim: string) => {
    setLoading(true);
    setActiveDim(dim);
    setMsg("");
    try {
      const text = await fetchDimension(dim);
      setContent(text);
      setOriginalContent(text);
    } catch {
      setContent("");
      setOriginalContent("");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDimension("basic_info");
  }, [loadDimension]);

  const handleSave = async () => {
    if (content === originalContent) return;
    setSaving(true);
    setMsg("");
    try {
      await updateDimension(activeDim, content);
      setOriginalContent(content);
      setMsg("已保存");
    } catch {
      setMsg("保存失败");
    } finally {
      setSaving(false);
    }
  };

  const modified = content !== originalContent;

  return (
    <div className="flex h-[calc(100vh-57px)]">
      {/* 左侧维度列表 */}
      <aside className="w-48 border-r border-white/10 overflow-y-auto shrink-0">
        {soulName && (
          <div className="px-4 py-3 text-sm font-medium text-white/60 border-b border-white/5">
            {soulName}
          </div>
        )}
        {DIMENSIONS.map((dim) => (
          <button
            key={dim}
            onClick={() => loadDimension(dim)}
            className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
              activeDim === dim
                ? "bg-white/10 text-white/80"
                : "text-white/40 hover:text-white/60 hover:bg-white/5"
            }`}
          >
            {DIMENSION_LABELS[dim]}
          </button>
        ))}
      </aside>

      {/* 右侧编辑器 */}
      <div className="flex-1 flex flex-col">
        <div className="flex items-center justify-between px-6 py-3 border-b border-white/10">
          <h3 className="text-sm text-white/50">{DIMENSION_LABELS[activeDim]}</h3>
          <button
            onClick={handleSave}
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

        {loading ? (
          <div className="flex-1 flex items-center justify-center text-white/20">加载中...</div>
        ) : (
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="flex-1 bg-transparent text-sm text-white/70 p-6 outline-none resize-none font-mono leading-relaxed"
            placeholder="暂无内容"
          />
        )}

        {msg && (
          <div className="px-6 py-2 border-t border-white/5 text-xs text-white/30">{msg}</div>
        )}
      </div>
    </div>
  );
}
