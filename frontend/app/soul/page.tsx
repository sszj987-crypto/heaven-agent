"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchSoul, fetchDimension, updateDimension,
  uploadVoiceSample, fetchCircumstances, updateCircumstances,
  fetchVoiceStatus, distillSoul, fetchSkill,
  fetchMemoryStats, fetchMemoryByDimension, deleteMemory,
  type SceneOption, type DistillResult, type MemoryStats, type MemoryEntry,
} from "@/lib/api";

const DIMENSION_LABELS: Record<string, string> = {
  basic_info: "基本信息",
  personality: "性格",
  life_experiences: "人生经历",
  relationships: "人际关系",
  personal_traits: "个人特质",
  emotional_anchors: "情感锚点",
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

  // 行为规则状态
  const [skillCard, setSkillCard] = useState<Record<string, string> | null>(null);
  const [skillLoading, setSkillLoading] = useState(false);

  // 蒸馏状态
  const [distillFile, setDistillFile] = useState<File | null>(null);
  const [distillChatName, setDistillChatName] = useState(soulName);
  const [distilling, setDistilling] = useState(false);
  const [distillResult, setDistillResult] = useState<DistillResult | null>(null);
  const [distillError, setDistillError] = useState("");
  const distillDropRef = useRef<HTMLDivElement>(null);
  const distillInputRef = useRef<HTMLInputElement>(null);

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
          setDistillChatName(match[1].trim());
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
    // 加载行为规则
    loadSkill();
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

  const loadSkill = useCallback(async () => {
    setSkillLoading(true);
    try {
      const data = await fetchSkill();
      setSkillCard(data);
    } catch {
      setSkillCard(null);
    } finally {
      setSkillLoading(false);
    }
  }, []);

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
    if (tab === "distill") {
      setActiveTab("distill");
      setLoading(false);
      setMsg("");
      setDistillError("");
      return;
    }
    if (tab === "skill") {
      setActiveTab("skill");
      setLoading(false);
      setMsg("");
      loadSkill();
      return;
    }
    if (tab === "memory") {
      setActiveTab("memory");
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

  const handleDistill = useCallback(async () => {
    if (!distillFile) return;
    setDistilling(true);
    setDistillError("");
    setDistillResult(null);
    try {
      const result = await distillSoul(distillFile, distillChatName || undefined);
      setDistillResult(result);
      // 蒸馏后刷新行为规则
      if (result.skill_card) {
        setSkillCard(result.skill_card);
      }
    } catch (err) {
      setDistillError(err instanceof Error ? err.message : "蒸馏失败");
    } finally {
      setDistilling(false);
    }
  }, [distillFile]);

  const isDimensionTab = activeTab !== "scene" && activeTab !== "voice" && activeTab !== "distill" && activeTab !== "skill" && activeTab !== "memory";
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
        <button
          onClick={() => switchTab("distill")}
          className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
            activeTab === "distill"
              ? "bg-white/10 text-white/80"
              : "text-white/40 hover:text-white/60 hover:bg-white/5"
          }`}
        >
          聊天记录蒸馏
        </button>
        <button
          onClick={() => switchTab("skill")}
          className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
            activeTab === "skill"
              ? "bg-white/10 text-white/80"
              : "text-white/40 hover:text-white/60 hover:bg-white/5"
          }`}
        >
          行为规则
        </button>
        <div className="border-t border-white/5 my-1" />
        <button
          onClick={() => switchTab("memory")}
          className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
            activeTab === "memory"
              ? "bg-white/10 text-white/80"
              : "text-white/40 hover:text-white/60 hover:bg-white/5"
          }`}
        >
          记忆可视化
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
      ) : activeTab === "distill" ? (
        <DistillPanel
          file={distillFile}
          onFileSelect={setDistillFile}
          chatName={distillChatName}
          onChatNameChange={setDistillChatName}
          distilling={distilling}
          result={distillResult}
          error={distillError}
          dropRef={distillDropRef}
          inputRef={distillInputRef}
          onDistill={handleDistill}
          onClear={() => { setDistillFile(null); setDistillResult(null); setDistillError(""); }}
          onDimensionClick={(dim) => loadDimension(dim)}
        />
      ) : activeTab === "skill" ? (
        <SkillPanel skillCard={skillCard} loading={skillLoading} onRefresh={loadSkill} />
      ) : activeTab === "memory" ? (
        <MemoryPanel />
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

function DistillPanel({
  file,
  onFileSelect,
  chatName,
  onChatNameChange,
  distilling,
  result,
  error,
  dropRef,
  inputRef,
  onDistill,
  onClear,
  onDimensionClick,
}: {
  file: File | null;
  onFileSelect: (f: File | null) => void;
  chatName: string;
  onChatNameChange: (v: string) => void;
  distilling: boolean;
  result: DistillResult | null;
  error: string;
  dropRef: React.RefObject<HTMLDivElement | null>;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onDistill: () => void;
  onClear: () => void;
  onDimensionClick: (dim: string) => void;
}) {
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f && f.name.endsWith(".txt")) {
      onFileSelect(f);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => setDragOver(false);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) onFileSelect(f);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center px-6 py-3 border-b border-white/10">
        <h3 className="text-sm text-white/50">聊天记录蒸馏</h3>
      </div>

      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        <p className="text-sm text-white/40 leading-relaxed">
          上传逝者生前的聊天记录文件（仅支持 .txt 格式），AI 将自动分析对话内容，
          提取人格特征并智能合并到灵魂档案的各个维度中。已有内容不会被覆盖，只有新发现或矛盾
          信息才会更新。
        </p>

        {/* 文件拖拽区域 */}
        <div
          ref={dropRef}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
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
            onChange={handleInputChange}
            className="hidden"
          />
          {file ? (
            <div className="space-y-1">
              <p className="text-sm text-white/70">{file.name}</p>
              <p className="text-xs text-white/30">
                {(file.size / 1024).toFixed(1)} KB
              </p>
            </div>
          ) : (
            <div className="space-y-1">
              <p className="text-sm text-white/40">
                拖拽 .txt 文件到此处，或点击选择文件
              </p>
              <p className="text-xs text-white/20">支持 UTF-8 编码 .txt 格式</p>
            </div>
          )}
        </div>

        {/* 聊天昵称 */}
        <div className="space-y-1">
          <label className="text-xs text-white/30">聊天中的昵称</label>
          <input
            type="text"
            value={chatName}
            onChange={(e) => onChatNameChange(e.target.value)}
            placeholder="输入目标人物在聊天记录中的名字"
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white/70 outline-none focus:border-white/30 transition-colors"
          />
          <p className="text-xs text-white/20">
            填写目标人物在聊天记录中显示的名字，如微信导出中常为"我"，请替换为实际姓名
          </p>
        </div>

        {/* 操作按钮 */}
        <div className="flex gap-3">
          <button
            onClick={(e) => { e.stopPropagation(); onDistill(); }}
            disabled={!file || distilling}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              file && !distilling
                ? "bg-blue-500/20 border border-blue-500/30 hover:bg-blue-500/30 text-white"
                : "bg-white/5 border border-white/10 text-white/20"
            }`}
          >
            {distilling ? "分析中..." : "开始分析"}
          </button>
          {file && !distilling && (
            <button
              onClick={onClear}
              className="px-4 py-2 text-sm rounded-lg bg-white/5 border border-white/10 text-white/40 hover:text-white/60 transition-colors"
            >
              清除
            </button>
          )}
        </div>

        {/* Loading */}
        {distilling && (
          <div className="flex items-center gap-3 text-sm text-white/30">
            <div className="w-4 h-4 border-2 border-white/20 border-t-white/60 rounded-full animate-spin" />
            AI 正在分析聊天记录，这可能需要几十秒...
          </div>
        )}

        {/* 错误 */}
        {error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
            <p className="text-sm text-red-400">{error}</p>
          </div>
        )}

        {/* 结果 */}
        {result && (
          <div className="space-y-4">
            {/* 摘要 */}
            {result.summary && (
              <div className="rounded-lg border border-white/10 bg-white/5 p-3">
                <p className="text-xs text-white/30 mb-1">分析摘要</p>
                <p className="text-sm text-white/70">{result.summary}</p>
              </div>
            )}

            {/* 变化维度 */}
            {result.changes.length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs text-white/30">
                  以下 {result.changes.length} 个维度已更新，点击可查看：
                </p>
                <div className="flex flex-wrap gap-2">
                  {result.changes.map((dim) => (
                    <button
                      key={dim}
                      onClick={() => onDimensionClick(dim)}
                      className="px-3 py-1.5 text-xs rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors"
                    >
                      {DIMENSION_LABELS[dim] || dim}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-white/10 bg-white/5 p-3">
                <p className="text-sm text-white/40">
                  未发现需要更新的维度，当前档案与聊天记录一致。
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const SKILL_SECTIONS: { key: string; label: string }[] = [
  { key: "role_playing_rules", label: "扮演规则" },
  { key: "expression_dna", label: "表达基因" },
  { key: "decision_heuristics", label: "决策启发式" },
  { key: "mental_models", label: "思维模型" },
  { key: "values_anti_patterns", label: "价值观与禁区" },
  { key: "inner_tensions", label: "内在矛盾" },
];

function SkillPanel({
  skillCard,
  loading,
  onRefresh,
}: {
  skillCard: Record<string, string> | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  const [activeSection, setActiveSection] = useState(SKILL_SECTIONS[0].key);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <span className="text-sm text-white/30">加载中...</span>
      </div>
    );
  }

  if (!skillCard) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4">
        <p className="text-sm text-white/40">暂无行为规则</p>
        <p className="text-xs text-white/20 max-w-md text-center">
          上传逝者聊天记录进行蒸馏分析，AI 将自动提取表达风格、
          决策模式、思维模型、价值观等行为规则，用于指导对话扮演。
        </p>
        <button
          onClick={onRefresh}
          className="px-3 py-1.5 text-xs rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
        >
          刷新
        </button>
      </div>
    );
  }

  const activeContent = skillCard[activeSection] || "";

  return (
    <div className="flex-1 flex flex-col">
      {/* 顶部标题 */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/10">
        <h3 className="text-sm text-white/50">行为规则</h3>
        <button
          onClick={onRefresh}
          className="px-3 py-1.5 text-xs rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
        >
          刷新
        </button>
      </div>

      {/* Section 子标签 */}
      <div className="flex gap-1 px-4 py-2 border-b border-white/5 overflow-x-auto">
        {SKILL_SECTIONS.map((s) => (
          <button
            key={s.key}
            onClick={() => setActiveSection(s.key)}
            className={`shrink-0 px-3 py-1 text-xs rounded-md transition-colors ${
              activeSection === s.key
                ? "bg-white/15 text-white/80"
                : "text-white/30 hover:text-white/50 hover:bg-white/5"
            }`}
          >
            {s.label}
            {skillCard[s.key] && (
              <span className="ml-1 text-green-400">●</span>
            )}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto p-6">
        {activeContent ? (
          <pre className="text-sm text-white/70 font-mono leading-relaxed whitespace-pre-wrap break-words">
            {activeContent}
          </pre>
        ) : (
          <p className="text-sm text-white/20 italic">此维度暂无内容</p>
        )}
      </div>
    </div>
  );
}

const MEMORY_DIMENSION_LABELS: Record<string, string> = {
  life_experiences: "人生经历",
  relationships: "人际关系",
  personal_traits: "个人特质",
  emotional_anchors: "情感锚点",
  basic_info: "基本信息",
  personality: "性格",
};

function MemoryPanel() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [selectedDim, setSelectedDim] = useState<string | null>(null);
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [dimLoading, setDimLoading] = useState(false);

  const loadStats = useCallback(async () => {
    setLoading(true);
    try {
      setStats(await fetchMemoryStats());
    } catch {
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDim = useCallback(async (dim: string) => {
    setDimLoading(true);
    setSelectedDim(dim);
    try {
      setEntries(await fetchMemoryByDimension(dim));
    } catch {
      setEntries([]);
    } finally {
      setDimLoading(false);
    }
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);

  const handleDelete = async (id: string) => {
    try {
      await deleteMemory(id);
      setEntries((prev) => prev.filter((e) => e.id !== id));
      loadStats();
    } catch {}
  };

  const dims = stats?.by_dimension ?? {};
  const dimList = Object.entries(dims).sort(([, a], [, b]) => b - a);
  const maxCount = Math.max(...Object.values(dims), 1);

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex items-center px-6 py-3 border-b border-white/10">
        <h3 className="text-sm text-white/50">记忆可视化</h3>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {loading ? (
          <div className="flex items-center justify-center py-12 text-white/20">加载中...</div>
        ) : !stats || stats.total === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <p className="text-sm text-white/40">暂无记忆数据</p>
            <p className="text-xs text-white/20">对话过程中系统会自动提取和存储记忆</p>
          </div>
        ) : (
          <>
            {/* 概览 */}
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
              <p className="text-sm text-white/60 mb-3">
                总计 <span className="text-white/80 font-medium">{stats.total}</span> 条记忆
              </p>
              <div className="space-y-2">
                {dimList.map(([dim, count]) => (
                  <button
                    key={dim}
                    onClick={() => loadDim(dim)}
                    className={`w-full flex items-center gap-3 text-left rounded-lg px-3 py-2 transition-colors ${
                      selectedDim === dim
                        ? "bg-white/10"
                        : "hover:bg-white/5"
                    }`}
                  >
                    <span className="text-xs text-white/50 w-24 shrink-0">
                      {MEMORY_DIMENSION_LABELS[dim] || dim}
                    </span>
                    <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-white/20 transition-all"
                        style={{ width: `${(count / maxCount) * 100}%` }}
                      />
                    </div>
                    <span className="text-xs text-white/30 w-6 text-right">{count}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* 维度详情 */}
            {selectedDim && (
              <div className="space-y-3">
                <h4 className="text-xs text-white/30">
                  {MEMORY_DIMENSION_LABELS[selectedDim] || selectedDim}
                  {" · "}{entries.length} 条
                </h4>
                {dimLoading ? (
                  <div className="text-xs text-white/20">加载中...</div>
                ) : entries.length === 0 ? (
                  <p className="text-xs text-white/20">该维度暂无记忆</p>
                ) : (
                  entries.map((entry) => {
                    const s = entry.metadata.strength ?? 0;
                    const pct = Math.round(s * 100);
                    const barColor =
                      s > 0.7 ? "bg-green-500/40" :
                      s > 0.4 ? "bg-yellow-500/40" :
                      "bg-red-500/40";
                    return (
                      <div
                        key={entry.id}
                        className="rounded-lg border border-white/5 bg-white/[0.02] p-3 group"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-sm text-white/70 leading-relaxed flex-1">
                            {entry.document}
                          </p>
                          <button
                            onClick={() => handleDelete(entry.id)}
                            className="shrink-0 opacity-0 group-hover:opacity-100 text-white/20 hover:text-red-400 transition-all text-xs"
                            title="删除此记忆"
                          >
                            ✕
                          </button>
                        </div>
                        <div className="flex items-center gap-3 mt-2">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[10px] text-white/30">强度</span>
                            <div className="w-12 h-1.5 rounded-full bg-white/5 overflow-hidden">
                              <div
                                className={`h-full rounded-full transition-all ${barColor}`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                            <span className="text-[10px] text-white/30">{pct}%</span>
                          </div>
                          {entry.metadata.access_count > 0 && (
                            <span className="text-[10px] text-white/20">
                              访问 {entry.metadata.access_count} 次
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}