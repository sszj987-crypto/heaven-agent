"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import CandidateInbox from "@/components/soul/CandidateInbox";
import DimensionEditor from "@/components/soul/DimensionEditor";
import DistillPanel from "@/components/soul/DistillPanel";
import MemoryPanel from "@/components/soul/MemoryPanel";
import ScenePanel from "@/components/soul/ScenePanel";
import SkillPanel from "@/components/soul/SkillPanel";
import SoulSidebar from "@/components/soul/SoulSidebar";
import VoicePanel from "@/components/soul/VoicePanel";
import { DIMENSIONS } from "@/components/soul/constants";
import {
  canEditSoulName,
  shouldApplyDimensionResponse,
  updateBasicInfoName,
} from "@/components/soul/profile-state";
import {
  fetchDimension,
  fetchSoul,
  markOnboardingStep,
  updateDimension,
} from "@/lib/api";


export default function SoulPage() {
  const [activeTab, setActiveTab] = useState("basic_info");
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [soulName, setSoulName] = useState("");
  const [originalName, setOriginalName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const dimensionRequest = useRef(0);

  const loadDimension = useCallback(async (dimension: string) => {
    const requestId = ++dimensionRequest.current;
    setActiveTab(dimension);
    setLoading(true);
    setMessage("");
    try {
      const text = await fetchDimension(dimension);
      if (!shouldApplyDimensionResponse(requestId, dimensionRequest.current)) return;
      setContent(text);
      setOriginalContent(text);
    } catch (error) {
      if (!shouldApplyDimensionResponse(requestId, dimensionRequest.current)) return;
      setContent("");
      setOriginalContent("");
      setMessage(error instanceof Error ? error.message : "档案加载失败");
    } finally {
      if (shouldApplyDimensionResponse(requestId, dimensionRequest.current)) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    let active = true;
    const requestId = ++dimensionRequest.current;
    fetchSoul()
      .then((profile) => {
        if (!active) return;
        const match = (profile.dimensions.basic_info || "").match(/姓名[：:]\s*(.+)/);
        if (match) {
          const name = match[1].trim();
          setSoulName(name);
          setOriginalName(name);
        }
      })
      .catch(() => undefined);
    fetchDimension("basic_info")
      .then((text) => {
        if (!active || !shouldApplyDimensionResponse(requestId, dimensionRequest.current)) return;
        setContent(text);
        setOriginalContent(text);
      })
      .catch((error: unknown) => {
        if (active && shouldApplyDimensionResponse(requestId, dimensionRequest.current)) {
          setMessage(error instanceof Error ? error.message : "档案加载失败");
        }
      })
      .finally(() => {
        if (active && shouldApplyDimensionResponse(requestId, dimensionRequest.current)) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const saveDimension = useCallback(async () => {
    if (!DIMENSIONS.includes(activeTab)) return;
    setSaving(true);
    setMessage("");
    let nextContent = content;
    if (activeTab === "basic_info" && soulName !== originalName) {
      nextContent = updateBasicInfoName(nextContent, soulName);
    }
    try {
      if (nextContent !== originalContent) {
        await updateDimension(activeTab, nextContent);
        setContent(nextContent);
        setOriginalContent(nextContent);
      }
      if (activeTab === "basic_info") {
        await markOnboardingStep("profile");
        setOriginalName(soulName);
      }
      setMessage("已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }, [activeTab, content, originalContent, originalName, soulName]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "s") {
        event.preventDefault();
        void saveDimension();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [saveDimension]);

  const modified =
    content !== originalContent ||
    (activeTab === "basic_info" && soulName !== originalName);

  return (
    <div className="flex min-h-0 flex-1">
      <SoulSidebar
        activeTab={activeTab}
        soulName={soulName}
        nameEditable={canEditSoulName(activeTab)}
        onNameChange={setSoulName}
        onSelect={(tab) => {
          setMessage("");
          if (DIMENSIONS.includes(tab)) {
            void loadDimension(tab);
          } else {
            dimensionRequest.current += 1;
            setActiveTab(tab);
            setLoading(false);
          }
        }}
      />
      {activeTab === "candidates" ? (
        <CandidateInbox />
      ) : activeTab === "scene" ? (
        <ScenePanel />
      ) : activeTab === "voice" ? (
        <VoicePanel />
      ) : activeTab === "distill" ? (
        <DistillPanel onDimensionClick={loadDimension} />
      ) : activeTab === "skill" ? (
        <SkillPanel />
      ) : activeTab === "memory" ? (
        <MemoryPanel />
      ) : (
        <DimensionEditor
          dimension={activeTab}
          content={content}
          loading={loading}
          saving={saving}
          modified={modified}
          message={message}
          onChange={setContent}
          onSave={saveDimension}
        />
      )}
    </div>
  );
}
