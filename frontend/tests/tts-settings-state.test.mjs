import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptTTSConnectionResult,
  buildTTSUpdate,
  invalidateTTSConnection,
  isTTSFormLocked,
  resetTTSFormAfterSave,
  runTTSConnectionTest,
} from "../components/settings/tts-settings-state.ts";


const minimaxForm = {
  provider: "minimax",
  auto_play: false,
  audio_cache_size: 10,
  base_url: "https://api.minimaxi.com",
  model: "speech-2.8-hd",
  api_key: "",
};


test("unchanged MiniMax key is omitted", () => {
  assert.deepEqual(buildTTSUpdate(minimaxForm, false), {
    provider: "minimax",
    auto_play: false,
    audio_cache_size: 10,
    minimax: {
      base_url: "https://api.minimaxi.com",
      model: "speech-2.8-hd",
    },
  });
});


test("explicit MiniMax key clear is preserved", () => {
  assert.equal(buildTTSUpdate(minimaxForm, true).minimax.api_key, "");
});


test("a replacement key is cleared after saving so an unrelated later save omits it", () => {
  const saved = resetTTSFormAfterSave({ ...minimaxForm, api_key: "new-secret" });

  assert.equal(saved.form.api_key, "");
  assert.equal(saved.keyDirty, false);
  assert.deepEqual(buildTTSUpdate({ ...saved.form, model: "speech-2.8-turbo" }, saved.keyDirty), {
    provider: "minimax",
    auto_play: false,
    audio_cache_size: 10,
    minimax: {
      base_url: "https://api.minimaxi.com",
      model: "speech-2.8-turbo",
    },
  });
});

test("auto play enabled survives save and secret reset", () => {
  const saved = resetTTSFormAfterSave({ ...minimaxForm, auto_play: true });
  assert.equal(buildTTSUpdate(saved.form, saved.keyDirty).auto_play, true);
});


test("connection results from before a configuration edit are ignored", () => {
  const started = { revision: 3, result: null, error: null };
  const edited = invalidateTTSConnection(started);

  assert.deepEqual(edited, { revision: 4, result: null, error: null });
  assert.deepEqual(acceptTTSConnectionResult(edited, 3, true), edited);
});


test("connection results for the current configuration are displayed", () => {
  const current = { revision: 4, result: null, error: null };

  assert.deepEqual(acceptTTSConnectionResult(current, 4, true), {
    revision: 4,
    result: true,
    error: null,
  });
});


test("connection errors are displayed only for the current configuration", () => {
  const current = { revision: 4, result: null, error: null };

  assert.deepEqual(acceptTTSConnectionResult(current, 4, null, "连接失败"), {
    revision: 4,
    result: null,
    error: "连接失败",
  });
  assert.deepEqual(acceptTTSConnectionResult(current, 3, null, "过期错误"), current);
});


test("saving locks all TTS form controls against concurrent edits", () => {
  assert.equal(isTTSFormLocked(true), true);
  assert.equal(isTTSFormLocked(false), false);
});

test("async connection checks display disconnected responses and safe failures", async () => {
  let status = { revision: 4, result: null, error: null };
  const update = change => { status = change(status); };
  await runTTSConnectionTest(4, async () => false, update);
  assert.deepEqual(status, { revision: 4, result: false, error: null });
  await runTTSConnectionTest(4, async () => { throw Error("无法连接语音服务"); }, update);
  assert.deepEqual(status, { revision: 4, result: null, error: "无法连接语音服务" });
});

test("async connection checks cannot publish success or error after configuration changes", async () => {
  for (const outcome of [true, Error("expired error")]) {
    let finish;
    let status = { revision: 4, result: null, error: null };
    const pending = runTTSConnectionTest(4, () => new Promise((resolve, reject) => {
      finish = () => outcome instanceof Error ? reject(outcome) : resolve(outcome);
    }), change => { status = change(status); });
    status = invalidateTTSConnection(status);
    finish();
    await pending;
    assert.deepEqual(status, { revision: 5, result: null, error: null });
  }
});
