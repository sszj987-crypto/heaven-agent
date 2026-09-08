"use client";

import { useRef, useState } from "react";

import { distillSoul, type DistillResult } from "@/lib/api";
import { DIMENSION_LABELS } from "./constants";


export default function DistillPanel({
  defaultChatName,
  onDimensionClick,
}: {
  defaultChatName: string;
  onDimensionClick: (dimension: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [chatName, setChatName] = useState(defaultChatName);
  const [dragOver, setDragOver] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<DistillResult | null>(null);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const selectFile = (candidate?: File) => {
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith(".txt")) {
      setError("只支持 .txt 格式的聊天记录");
      return;
    }
    setFile(candidate);
    setResult(null);
    setError("");
  };

  const run = async () => {
    if (!file) return;
    setRunning(true);
    setResult(null);
    setError("");
    try {
      setResult(await distillSoul(file, chatName || undefined));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "导入分析失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center px-6 py-3 border-b border-white/10">
        <h3 className="text-sm text-white/50">聊天记录导入</h3>
      </div>
      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        <p className="text-sm text-white/40 leading-relaxed">
          上传 UTF-8 编码的 .txt 聊天记录。分析结果只会进入待确认事实收件箱，不会直接改写人物档案。
        </p>
        <div
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            selectFile(event.dataTransfer.files[0]);
          }}
          onDragOver={(event) => {
            event.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
            dragOver
              ? "border-blue-400 bg-blue-500/10"
              : file
                ? "border-green-500/30 bg-green-500/5"
                : "border-white/10 hover:border-white/20 bg-white/[0.02]"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".txt"
            onChange={(event) => {
              selectFile(event.target.files?.[0]);
              event.target.value = "";
            }}
            className="hidden"
          />
          <p className="text-sm text-white/50">
            {file ? file.name : "拖拽 .txt 文件到此处，或点击选择"}
          </p>
          {file && <p className="text-xs text-white/30 mt-1">{(file.size / 1024).toFixed(1)} KB</p>}
        </div>
        <div className="space-y-1">
          <label className="text-xs text-white/30">目标人物在聊天中的昵称</label>
          <input
            value={chatName}
            onChange={(event) => setChatName(event.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white/70 outline-none focus:border-white/30"
            placeholder="例如：奶奶"
          />
        </div>
        <div className="flex gap-3">
          <button
            onClick={run}
            disabled={!file || running}
            className="px-4 py-2 text-sm rounded-lg bg-blue-500/20 border border-blue-500/30 disabled:opacity-30"
          >
            {running ? "分析中..." : "开始分析"}
          </button>
          {file && !running && (
            <button
              onClick={() => {
                setFile(null);
                setResult(null);
                setError("");
              }}
              className="px-4 py-2 text-sm rounded-lg bg-white/5 border border-white/10 text-white/40"
            >
              清除
            </button>
          )}
        </div>
        {error && <p className="text-sm text-red-400">{error}</p>}
        {result && (
          <div className="space-y-4 rounded-xl border border-white/10 bg-white/[0.02] p-4">
            <p className="text-sm text-white/70">{result.summary || "分析完成"}</p>
            <p className="text-xs text-amber-200/70">
              已生成 {result.candidate_count ?? result.candidate_ids?.length ?? result.changes.length} 条待确认候选，档案尚未修改。
            </p>
            <div className="flex flex-wrap gap-2">
              {result.changes.map((dimension) => (
                <button
                  key={dimension}
                  onClick={() => onDimensionClick(dimension)}
                  className="px-3 py-1.5 text-xs rounded-lg bg-green-500/10 border border-green-500/30 text-green-400"
                >
                  {DIMENSION_LABELS[dimension] || dimension}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
