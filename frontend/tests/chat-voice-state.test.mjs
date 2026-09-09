import assert from "node:assert/strict";
import test from "node:test";

import {
  createAssistantMessage,
  voicePhasePresentation,
  withAudioState,
} from "../app/chat/chat-state.ts";


test("recording and transcription belong to the user side", () => {
  assert.deepEqual(voicePhasePresentation("recording"), {
    side: "user",
    label: "你正在说话…",
  });
  assert.deepEqual(voicePhasePresentation("transcribing"), {
    side: "user",
    label: "正在识别你的语音…",
  });
  assert.deepEqual(voicePhasePresentation("replying"), {
    side: "assistant",
    label: "正在回复…",
  });
});


test("assistant messages expose text immediately with parameters for background preparation", () => {
  const message = createAssistantMessage({
    responseText: "欢迎回来",
    hasVoice: true,
    audioParams: { text: "欢迎回来", instructText: "温柔地说" },
    usedMemories: [],
    safetyState: "normal",
  });

  assert.equal(message.content, "欢迎回来");
  assert.equal(message.audioState, "idle");
  assert.deepEqual(message.audioParams, {
    text: "欢迎回来",
    instructText: "温柔地说",
  });
  assert.equal(message.audioUrl, undefined);
});


test("voice preparation failure keeps text and remains retryable", () => {
  const message = createAssistantMessage({
    responseText: "欢迎回来",
    hasVoice: true,
    audioParams: { text: "欢迎回来", instructText: "温柔地说" },
    usedMemories: [],
    safetyState: "normal",
  });

  const failed = withAudioState(message, "error", "语音准备失败，请重试");

  assert.equal(failed.content, "欢迎回来");
  assert.equal(failed.audioState, "error");
  assert.equal(failed.audioError, "语音准备失败，请重试");
  assert.ok(failed.audioParams);
});
