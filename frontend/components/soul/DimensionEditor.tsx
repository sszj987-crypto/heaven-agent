import { DIMENSION_LABELS } from "./constants";


export default function DimensionEditor({
  dimension,
  content,
  loading,
  saving,
  modified,
  message,
  onChange,
  onSave,
}: {
  dimension: string;
  content: string;
  loading: boolean;
  saving: boolean;
  modified: boolean;
  message: string;
  onChange: (content: string) => void;
  onSave: () => void;
}) {
  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/10">
        <h3 className="text-sm text-white/50">{DIMENSION_LABELS[dimension]}</h3>
        <button
          onClick={onSave}
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
          onChange={(event) => onChange(event.target.value)}
          className="flex-1 bg-transparent text-sm text-white/70 p-6 outline-none resize-none font-mono leading-relaxed"
          placeholder="暂无内容"
        />
      )}
      {message && (
        <div className="px-6 py-2 border-t border-white/5 text-xs text-white/30">
          {message}
        </div>
      )}
    </div>
  );
}
