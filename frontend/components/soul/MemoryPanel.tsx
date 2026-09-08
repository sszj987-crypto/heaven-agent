"use client";

import { useCallback, useEffect, useState } from "react";

import {
  deleteMemory,
  fetchMemoryByDimension,
  fetchMemoryStats,
  type MemoryEntry,
  type MemoryStats,
} from "@/lib/api";
import { DIMENSION_LABELS } from "./constants";


export default function MemoryPanel() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const loadStats = useCallback(async () => {
    setLoading(true);
    try {
      setStats(await fetchMemoryStats());
      setError("");
    } catch (caught) {
      setStats(null);
      setError(caught instanceof Error ? caught.message : "记忆索引不可用");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    fetchMemoryStats()
      .then((result) => {
        if (active) setStats(result);
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "记忆索引不可用");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const loadDimension = async (dimension: string) => {
    setSelected(dimension);
    setDetailLoading(true);
    try {
      setEntries(await fetchMemoryByDimension(dimension));
      setError("");
    } catch (caught) {
      setEntries([]);
      setError(caught instanceof Error ? caught.message : "记忆加载失败");
    } finally {
      setDetailLoading(false);
    }
  };

  const dimensions = Object.entries(stats?.by_dimension ?? {}).sort(([, left], [, right]) => right - left);
  const maxCount = Math.max(...dimensions.map(([, count]) => count), 1);

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center px-6 py-3 border-b border-white/10">
        <h3 className="text-sm text-white/50">记忆可视化</h3>
      </div>
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {loading ? (
          <div className="py-12 text-center text-white/20">加载中...</div>
        ) : !stats || stats.total === 0 ? (
          <div className="py-12 text-center space-y-2">
            <p className="text-sm text-white/40">暂无对话记忆</p>
            <p className="text-xs text-white/20">人物档案仍是事实真源；对话摘要仅用于检索。</p>
            {error && <p className="text-xs text-red-400">{error}</p>}
          </div>
        ) : (
          <>
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4 space-y-2">
              <p className="text-sm text-white/60 mb-3">总计 {stats.total} 条记忆</p>
              {dimensions.map(([dimension, count]) => (
                <button
                  key={dimension}
                  onClick={() => loadDimension(dimension)}
                  className={`w-full flex items-center gap-3 text-left rounded-lg px-3 py-2 ${
                    selected === dimension ? "bg-white/10" : "hover:bg-white/5"
                  }`}
                >
                  <span className="text-xs text-white/50 w-24 shrink-0">
                    {DIMENSION_LABELS[dimension] || dimension}
                  </span>
                  <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
                    <div className="h-full bg-white/20" style={{ width: `${(count / maxCount) * 100}%` }} />
                  </div>
                  <span className="text-xs text-white/30">{count}</span>
                </button>
              ))}
            </div>
            {selected && (
              <div className="space-y-3">
                <h4 className="text-xs text-white/30">
                  {DIMENSION_LABELS[selected] || selected} · {entries.length} 条
                </h4>
                {detailLoading ? (
                  <p className="text-xs text-white/20">加载中...</p>
                ) : entries.map((entry) => (
                  <MemoryRow
                    key={entry.id}
                    entry={entry}
                    onDelete={async () => {
                      if (!confirm("确定删除这条可重建记忆吗？")) return;
                      try {
                        await deleteMemory(entry.id);
                        setEntries((current) => current.filter((item) => item.id !== entry.id));
                        await loadStats();
                      } catch (caught) {
                        setError(caught instanceof Error ? caught.message : "删除失败");
                      }
                    }}
                  />
                ))}
                {error && <p className="text-xs text-red-400">{error}</p>}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}


function MemoryRow({ entry, onDelete }: { entry: MemoryEntry; onDelete: () => void }) {
  const strength = entry.metadata.strength ?? 0;
  const percentage = Math.round(strength * 100);
  const barColor = strength > 0.7 ? "bg-green-500/40" : strength > 0.4 ? "bg-yellow-500/40" : "bg-red-500/40";
  return (
    <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3 group">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-white/70 leading-relaxed flex-1">{entry.document}</p>
        <button onClick={onDelete} className="text-white/20 hover:text-red-400 text-xs" title="删除此记忆">✕</button>
      </div>
      <div className="flex items-center gap-2 mt-2 text-[10px] text-white/30">
        <span>强度</span>
        <div className="w-12 h-1.5 rounded-full bg-white/5 overflow-hidden">
          <div className={`h-full ${barColor}`} style={{ width: `${percentage}%` }} />
        </div>
        <span>{percentage}%</span>
        {entry.metadata.access_count > 0 && <span>访问 {entry.metadata.access_count} 次</span>}
      </div>
    </div>
  );
}
