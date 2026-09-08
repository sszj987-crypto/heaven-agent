"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchSkill } from "@/lib/api";


const SECTIONS = [
  ["role_playing_rules", "扮演规则"],
  ["expression_dna", "表达基因"],
  ["decision_heuristics", "决策启发式"],
  ["mental_models", "思维模型"],
  ["values_anti_patterns", "价值观与禁区"],
  ["inner_tensions", "内在矛盾"],
] as const;


export default function SkillPanel() {
  const [card, setCard] = useState<Record<string, string> | null>(null);
  const [active, setActive] = useState<string>(SECTIONS[0][0]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setCard(await fetchSkill());
    } catch {
      setCard(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    fetchSkill()
      .then((result) => {
        if (active) setCard(result);
      })
      .catch(() => {
        if (active) setCard(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  if (loading) {
    return <div className="flex-1 flex items-center justify-center text-white/30">加载中...</div>;
  }
  if (!card) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4">
        <p className="text-sm text-white/40">暂无行为规则</p>
        <p className="text-xs text-white/20 max-w-md text-center">
          导入聊天记录并人工确认后，可形成更稳定的表达与行为规则。
        </p>
        <button onClick={load} className="px-3 py-1.5 text-xs rounded-lg bg-white/10">
          刷新
        </button>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/10">
        <h3 className="text-sm text-white/50">行为规则</h3>
        <button onClick={load} className="px-3 py-1.5 text-xs rounded-lg bg-white/10">刷新</button>
      </div>
      <div className="flex gap-1 px-4 py-2 border-b border-white/5 overflow-x-auto">
        {SECTIONS.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setActive(key)}
            className={`shrink-0 px-3 py-1 text-xs rounded-md ${
              active === key ? "bg-white/15 text-white/80" : "text-white/30 hover:bg-white/5"
            }`}
          >
            {label}{card[key] && <span className="ml-1 text-green-400">●</span>}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-6">
        {card[active] ? (
          <pre className="text-sm text-white/70 font-mono leading-relaxed whitespace-pre-wrap break-words">
            {card[active]}
          </pre>
        ) : (
          <p className="text-sm text-white/20 italic">此维度暂无内容</p>
        )}
      </div>
    </div>
  );
}
