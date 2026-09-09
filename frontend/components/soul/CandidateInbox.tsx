"use client";

import { useCallback, useEffect, useState } from "react";
import {
  approveMemoryCandidate,
  fetchMemoryCandidates,
  markOnboardingStep,
  rejectMemoryCandidate,
  type MemoryCandidate,
} from "@/lib/api";

const labels: Record<string, string> = {
  life_experiences: "人生经历",
  relationships: "人际关系",
  personal_traits: "个人特质",
  emotional_anchors: "情感锚点",
};

export default function CandidateInbox() {
  const [items, setItems] = useState<MemoryCandidate[]>([]);
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [completing, setCompleting] = useState(false);
  const [completed, setCompleted] = useState(false);

  useEffect(() => {
    fetchMemoryCandidates()
      .then(setItems)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  const resolve = useCallback(async (item: MemoryCandidate, approve: boolean) => {
    setError("");
    try {
      if (approve) await approveMemoryCandidate(item.id, editing[item.id] ?? item.content);
      else await rejectMemoryCandidate(item.id);
      setItems((current) => current.filter((candidate) => candidate.id !== item.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    }
  }, [editing]);

  const completeReview = useCallback(async () => {
    setCompleting(true);
    setError("");
    try {
      await markOnboardingStep("import_review");
      setCompleted(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法完成确认步骤");
    } finally {
      setCompleting(false);
    }
  }, []);

  return (
    <section className="flex-1 overflow-y-auto p-6 md:p-8">
      <div className="mx-auto max-w-3xl">
        <p className="text-xs tracking-[0.25em] text-amber-100/30">待确认</p>
        <h2 className="mt-2 text-xl font-light text-stone-100">决定哪些内容会成为人物事实</h2>
        <p className="mt-2 text-sm leading-6 text-stone-500">模型回复不会自动写入档案。只有你确认的候选内容才会长期影响后续对话。</p>

        {error && <p className="mt-5 rounded-xl bg-red-950/30 px-4 py-3 text-sm text-red-200/70">{error}</p>}
        {loading ? (
          <p className="mt-10 text-sm text-stone-500">正在读取候选事实…</p>
        ) : items.length === 0 ? (
          <div className="mt-10 rounded-2xl border border-white/5 bg-white/[0.02] p-8 text-center text-sm text-stone-500">
            <p>{completed ? "候选事实确认步骤已完成" : "没有待确认内容"}</p>
            {!completed && (
              <button
                onClick={completeReview}
                disabled={completing}
                className="mt-4 rounded-full bg-amber-100 px-4 py-2 text-xs text-stone-950 disabled:opacity-50"
              >
                {completing ? "记录中…" : "确认完成此步骤"}
              </button>
            )}
          </div>
        ) : (
          <div className="mt-8 space-y-4">
            {items.map((item) => (
              <article key={item.id} className="rounded-2xl border border-amber-100/10 bg-stone-900/70 p-5">
                <div className="flex items-center justify-between gap-4">
                  <span className="text-xs text-amber-100/50">{labels[item.dimension] ?? item.dimension}</span>
                  <span className="text-xs text-stone-600">置信度 {Math.round(item.confidence * 100)}%</span>
                </div>
                <textarea
                  value={editing[item.id] ?? item.content}
                  onChange={(event) => setEditing((current) => ({ ...current, [item.id]: event.target.value }))}
                  className="mt-3 min-h-20 w-full resize-y rounded-xl border border-white/5 bg-black/20 p-3 text-sm leading-6 text-stone-200 outline-none focus:border-amber-100/20"
                />
                <details className="mt-3 text-xs text-stone-500">
                  <summary className="cursor-pointer">查看来源</summary>
                  {item.source_speaker && <p className="mt-2">选定发言人：{item.source_speaker}</p>}
                  <p className="mt-2 whitespace-pre-wrap rounded-lg bg-black/20 p-3 leading-5">{item.source_excerpt}</p>
                </details>
                <div className="mt-4 flex gap-2">
                  <button onClick={() => resolve(item, true)} className="rounded-full bg-amber-100 px-4 py-2 text-xs text-stone-950 hover:bg-amber-50">确认写入</button>
                  <button onClick={() => resolve(item, false)} className="rounded-full border border-white/10 px-4 py-2 text-xs text-stone-400 hover:border-white/20">忽略</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
