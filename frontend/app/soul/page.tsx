"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchSoul, fetchDimension, updateDimension,
  uploadVoiceSample, fetchCircumstances, updateCircumstances,
  fetchVoiceStatus,
  type SceneOption,
} from "@/lib/api";

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

type Tab = string; // dimension key or "voice" or "scene"

export default function SoulPage() {
  const [activeTab, setActiveTab] = useState<Tab>("basic_info");
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [soulName, setSoulName] = useState("");
  const [originalName, setOriginalName] = useState("");

  // 声纹状态 —— 优先从 localStorage 读取，避免页面切换后闪烁
  const [voiceReady, setVoiceReady] = useState(() => {
    try {
      return localStorage.getItem("voice_ready") === "true";
    } catch {
      return false;
    }
  });
  const [recording, setRecording] = useState(false);
  const [uploadingVoice, setUploadingVoice] = useState(false);
  const [voiceMsg, setVoiceMsg] = useState("");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 场景状态
  const [sceneContent, setSceneContent] = useState("");
  const [originalSceneContent, setOriginalSceneContent] = useState("");
  const [scenes, setScenes] = useState<SceneOption[]>([]);
  const [currentSceneKey, setCurrentSceneKey] = useState("");

  // 初始加载
  useEffect(() => {
    // 加载灵魂信息
    fetchSoul()
      .then((profile) => {
        const basicInfo = profile.dimensions.basic_info || "";
        // 从 basic_info 中提取姓名
        const match = basicInfo.match(/姓名[：:]\s*(.+)/);
        if (match) {
          setSoulName(match[1].trim());
          setOriginalName(match[1].trim());
        }
      })
      .catch(() => {});
    // 加载场景
    fetchCircumstances()
      .then((data) => {
        setSceneContent(data.content);
        setOriginalSceneContent(data.content);
        setScenes(data.scenes);
        setCurrentSceneKey(data.scene);
      })
      .catch(() => {});
    // 异步校验声音档案状态，同步更新 localStorage
    fetchVoiceStatus()
      .then((s) => {
        setVoiceReady(s.has_reference);
        try { localStorage.setItem("voice_ready", String(s.has_reference)); } catch {}
      })
      .catch(() => {});
  }, []);

  const loadDimension = useCallback(async (dim: string) => {
    setLoading(true);
    setActiveTab(dim);
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

  const switchTab = (tab: Tab) => {
    if (tab === "voice") {
      setActiveTab("voice");
      setLoading(false);
      setMsg("");
      return;
    }
    if (tab === "scene") {
      setActiveTab("scene");
      setLoading(false);
      setMsg("");
      return;
    }
    loadDimension(tab);
  };

  // 应用预设场景模板
  const applySceneTemplate = (key: string) => {
    const scene = scenes.find((s) => s.key === key);
    if (!scene) return;
    // 场景数据从后端获取，这里需要后端返回 prompt
    // 暂时通过重新获取来加载
  };

  // 统一下保存
  const handleSave = async () => {
    setSaving(true);
    setMsg("");
    const errors: string[] = [];

    try {
      if (activeTab === "scene") {
        // 保存场景
        if (sceneContent !== originalSceneContent) {
          await updateCircumstances(sceneContent);
          setOriginalSceneContent(sceneContent);
        }
      } else if (activeTab === "voice") {
        // 声纹页无文字保存
      } else {
        // 保存当前维度，同时处理名称变更
        let dimensionContent = content;
        if (activeTab === "basic_info" && soulName !== originalName) {
          // 更新 basic_info 中的姓名
          dimensionContent = dimensionContent.replace(
            /姓名[：:]\s*.+/,
            `姓名: ${soulName}`
          );
          setContent(dimensionContent);
          setOriginalName(soulName);
        }
        if (dimensionContent !== originalContent) {
          await updateDimension(activeTab, dimensionContent);
          setOriginalContent(dimensionContent);
        }
      }
      setMsg("已保存");
    } catch {
      setMsg("保存失败");
    } finally {
      setSaving(false);
    }
  };

  // 声纹录制
  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        await submitVoiceSample(blob);
      };

      mediaRecorder.start();
      setRecording(true);
      setVoiceMsg("");
    } catch {
      setVoiceMsg("无法访问麦克风，请检查浏览器权限");
    }
  }, []);

  const stopRecording = useCallback(() => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }, []);

  const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await submitVoiceSample(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const submitVoiceSample = useCallback(async (audioBlob: Blob) => {
    setUploadingVoice(true);
    setVoiceMsg("");
    try {
      await uploadVoiceSample(audioBlob);
      setVoiceReady(true);
      try { localStorage.setItem("voice_ready", "true"); } catch {}
      setVoiceMsg("音色创建成功，后端已保存");
    } catch (err) {
      setVoiceMsg(err instanceof Error ? err.message : "音色上传失败");
    } finally {
      setUploadingVoice(false);
    }
  }, []);

  const isDimensionTab = activeTab !== "scene" && activeTab !== "voice";
  const isModified = isDimensionTab
    ? content !== originalContent || (activeTab === "basic_info" && soulName !== originalName)
    : activeTab === "scene"
      ? sceneContent !== originalSceneContent
      : false;

  // 快捷键保存 Ctrl/Cmd+S
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  return (
    <div className="flex h-[calc(100vh-57px)]">
      {/* 左侧维度列表 */}
      <aside className="w-48 border-r border-white/10 overflow-y-auto shrink-0 flex flex-col">
        {/* 可编辑的名字 */}
        <div className="px-3 py-2 border-b border-white/5">
          <input
            value={soulName}
            onChange={(e) => setSoulName(e.target.value)}
            className="w-full bg-transparent text-sm font-medium text-white/70 outline-none border border-transparent focus:border-white/20 rounded px-1.5 py-0.5 transition-colors"
            placeholder="输入姓名"
          />
        </div>
        {DIMENSIONS.map((dim) => (
          <button
            key={dim}
            onClick={() => switchTab(dim)}
            className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
              activeTab === dim
                ? "bg-white/10 text-white/80"
                : "text-white/40 hover:text-white/60 hover:bg-white/5"
            }`}
          >
            {DIMENSION_LABELS[dim]}
          </button>
        ))}
        <div className="border-t border-white/5 my-1" />
        <button
          onClick={() => switchTab("scene")}
          className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
            activeTab === "scene"
              ? "bg-white/10 text-white/80"
              : "text-white/40 hover:text-white/60 hover:bg-white/5"
          }`}
        >
          所在场景
        </button>
        <button
          onClick={() => switchTab("voice")}
          className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
            activeTab === "voice"
              ? "bg-white/10 text-white/80"
              : "text-white/40 hover:text-white/60 hover:bg-white/5"
          }`}
        >
          语音音色
        </button>
      </aside>

      {/* 右侧面板 */}
      {activeTab === "voice" ? (
        <VoicePanel
          voiceReady={voiceReady}
          voiceMsg={voiceMsg}
          recording={recording}
          uploadingVoice={uploadingVoice}
          fileInputRef={fileInputRef}
          onStartRecording={startRecording}
          onStopRecording={stopRecording}
          onFileUpload={handleFileUpload}
        />
      ) : activeTab === "scene" ? (
        <ScenePanel
          content={sceneContent}
          onChange={setSceneContent}
          onSelectScene={setCurrentSceneKey}
          scenes={scenes}
          currentSceneKey={currentSceneKey}
          saving={saving}
          isModified={sceneContent !== originalSceneContent}
          onSave={handleSave}
          msg={msg}
        />
      ) : (
        <div className="flex-1 flex flex-col">
          <div className="flex items-center justify-between px-6 py-3 border-b border-white/10">
            <h3 className="text-sm text-white/50">{DIMENSION_LABELS[activeTab]}</h3>
            <button
              onClick={handleSave}
              disabled={!isModified || saving}
              className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                isModified
                  ? "bg-white/20 text-white hover:bg-white/30"
                  : "bg-white/5 text-white/20"
              }`}
            >
              {saving ? "保存中..." : isModified ? "保存" : "已保存"}
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
      )}
    </div>
  );
}

function ScenePanel({
  content,
  onChange,
  onSelectScene,
  scenes,
  currentSceneKey,
  saving,
  isModified,
  onSave,
  msg,
}: {
  content: string;
  onChange: (v: string) => void;
  onSelectScene: (key: string) => void;
  scenes: SceneOption[];
  currentSceneKey: string;
  saving: boolean;
  isModified: boolean;
  onSave: () => void;
  msg: string;
}) {
  const handlePresetClick = (s: SceneOption) => {
    onChange(s.prompt);
    onSelectScene(s.key);
  };

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/10">
        <div className="flex items-center gap-3">
          <h3 className="text-sm text-white/50">逝者所在场景</h3>
          <span className={`text-xs px-2 py-0.5 rounded ${
            currentSceneKey === "custom"
              ? "bg-white/5 text-white/30"
              : "bg-white/10 text-white/50"
          }`}>
            {currentSceneKey === "heaven" ? "天堂（预设）" : currentSceneKey === "custom" ? "自定义" : currentSceneKey}
          </span>
        </div>
        <button
          onClick={onSave}
          disabled={!isModified || saving}
          className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
            isModified
              ? "bg-white/20 text-white hover:bg-white/30"
              : "bg-white/5 text-white/20"
          }`}
        >
          {saving ? "保存中..." : isModified ? "保存" : "已保存"}
        </button>
      </div>

      {/* 预设场景选项 */}
      <div className="px-6 py-3 border-b border-white/5">
        <div className="text-xs text-white/30 mb-2">选择预设场景，或直接在下方编辑器中自定义</div>
        <div className="flex gap-2 flex-wrap">
          {(scenes || []).map((s) => (
            <button
              key={s.key}
              onClick={() => handlePresetClick(s)}
              className={`px-3 py-1.5 text-xs rounded-lg border transition-all ${
                currentSceneKey === s.key
                  ? "bg-white/10 border-white/30 text-white/80"
                  : "bg-white/5 border-white/10 text-white/40 hover:border-white/20 hover:text-white/60"
              }`}
            >
              {s.label}
              {currentSceneKey === s.key && (
                <span className="ml-1.5 text-green-400">✓</span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 p-6 pb-0 overflow-y-auto">
        <textarea
          value={content}
          onChange={(e) => onChange(e.target.value)}
          className="w-full h-full min-h-[300px] bg-transparent text-sm text-white/70 outline-none resize-none font-mono leading-relaxed"
          placeholder="场景描述..."
        />
      </div>

      {msg && (
        <div className="px-6 py-2 border-t border-white/5 text-xs text-white/30">{msg}</div>
      )}
    </div>
  );
}

function VoicePanel({
  voiceReady,
  voiceMsg,
  recording,
  uploadingVoice,
  fileInputRef,
  onStartRecording,
  onStopRecording,
  onFileUpload,
}: {
  voiceReady: boolean;
  voiceMsg: string;
  recording: boolean;
  uploadingVoice: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onStartRecording: () => void;
  onStopRecording: () => void;
  onFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center px-6 py-3 border-b border-white/10">
        <h3 className="text-sm text-white/50">语音音色</h3>
      </div>

      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        {/* 声音档案状态卡片 */}
        <div className={`rounded-xl border p-4 flex items-center gap-3 ${voiceReady ? "border-green-500/30 bg-green-500/5" : "border-white/10 bg-white/5"}`}>
          <div className={`w-3 h-3 rounded-full ${voiceReady ? "bg-green-400" : "bg-white/20"}`} />
          <span className="text-sm">
            {voiceReady ? "声音档案已就绪，对话时将使用此音色合成语音" : "尚未上传声音档案，对话时将使用默认音色"}
          </span>
        </div>

        <p className="text-sm text-white/40 leading-relaxed">
          为灵魂注入声音——上传或录制逝者生前的语音样本（如语音消息、视频片段），系统将根据此样本合成相似音色。建议 10-30 秒清晰语音。
        </p>

        <div className="space-y-3">
          <div className="flex gap-3 items-center">
            {!recording ? (
              <button
                onClick={onStartRecording}
                disabled={uploadingVoice}
                className="px-4 py-2 text-sm rounded-lg bg-red-500/20 border border-red-500/30 hover:bg-red-500/30 transition-colors"
              >
                录制逝者声音
              </button>
            ) : (
              <button
                onClick={onStopRecording}
                className="px-4 py-2 text-sm rounded-lg bg-red-500/40 border border-red-500/50 animate-pulse transition-colors"
              >
                停止录制
              </button>
            )}

            <span className="text-xs text-white/20">或</span>

            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadingVoice || recording}
              className="px-4 py-2 text-sm rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
            >
              上传逝者音频文件
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="audio/*"
              onChange={onFileUpload}
              className="hidden"
            />
          </div>

          {uploadingVoice && (
            <p className="text-xs text-white/30">正在上传并创建声纹...</p>
          )}
          {voiceMsg && (
            <p className={`text-xs ${voiceMsg.includes("成功") ? "text-green-400" : "text-red-400"}`}>
              {voiceMsg}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}