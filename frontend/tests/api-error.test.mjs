import assert from "node:assert/strict";
import test from "node:test";

import {
  fetchAudio,
  fetchVoiceInstallation,
  formatApiError,
  installVoice,
  markOnboardingStep,
  resetDemo,
  testTTSConnection,
} from "../lib/api.ts";


test("uses the unified API error message", () => {
  assert.equal(
    formatApiError({ message: "候选事实已经处理" }, 409, "操作失败"),
    "候选事实已经处理",
  );
});


test("keeps compatibility with legacy detail errors", () => {
  assert.equal(
    formatApiError({ detail: "旧格式错误" }, 400, "操作失败"),
    "旧格式错误",
  );
});


test("falls back to a useful status message", () => {
  assert.equal(formatApiError({}, 503, "语音不可用"), "语音不可用 (503)");
});


test("demo reset uses an explicit POST and returns the backup name", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (_url, init) => {
    assert.equal(init?.method, "POST");
    assert.equal(init?.headers?.["X-Heaven-Action"], "demo-reset");
    return new Response(JSON.stringify({ status: "ok", recoverable: true, backup: "reset-1" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    assert.equal(await resetDemo(), "reset-1");
  } finally {
    globalThis.fetch = previousFetch;
  }
});


test("onboarding progress is recorded as an explicit step", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.match(String(url), /\/system\/onboarding\/steps\/import_review$/);
    assert.equal(init?.method, "POST");
    return new Response(JSON.stringify({ onboarding: {} }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    await markOnboardingStep("import_review");
  } finally {
    globalThis.fetch = previousFetch;
  }
});


test("voice installation uses the system endpoint and explicit confirmation", async () => {
  const previousFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([String(url), init]);
    if (init?.method === "POST") {
      return new Response(JSON.stringify({ job_id: "job_voice" }), { status: 202 });
    }
    return new Response(JSON.stringify({
      state: "not_installed",
      stage: "idle",
      message: "语音组件未安装",
      restart_required: false,
      job_id: null,
    }), { status: 200 });
  };
  try {
    assert.equal((await fetchVoiceInstallation()).state, "not_installed");
    assert.equal(await installVoice(), "job_voice");
    assert.match(calls[0][0], /\/system\/voice-installation$/);
    assert.equal(calls[1][1]?.method, "POST");
    assert.equal(calls[1][1]?.headers?.["X-Heaven-Action"], "install-voice");
  } finally {
    globalThis.fetch = previousFetch;
  }
});


test("audio client rejects a zero-byte successful response", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(new Blob([]), {
    status: 200,
    headers: { "content-type": "audio/wav" },
  });
  try {
    await assert.rejects(
      () => fetchAudio({ text: "你好", instructText: "平静地说" }),
      /语音准备失败，请重试/,
    );
  } finally {
    globalThis.fetch = previousFetch;
  }
});


test("TTS connection test posts saved settings and returns its boolean", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.match(String(url), /\/settings\/test-tts$/);
    assert.equal(init?.method, "POST");
    return new Response(JSON.stringify({ connected: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    assert.equal(await testTTSConnection(), true);
  } finally {
    globalThis.fetch = previousFetch;
  }
});


test("TTS connection test surfaces safe backend errors", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json(
    { message: "MiniMax 请求频率受限，请稍后重试" },
    { status: 502 },
  ));

  await assert.rejects(testTTSConnection, /MiniMax 请求频率受限，请稍后重试/);
});


test("TTS connection test distinguishes a valid disconnected response", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ connected: false }));

  assert.equal(await testTTSConnection(), false);
});


test("TTS connection test maps network and invalid JSON failures to safe messages", async (t) => {
  t.mock.method(globalThis, "fetch", async () => { throw new Error("PRIVATE_NETWORK_DETAIL"); });
  await assert.rejects(testTTSConnection, /^Error: 无法连接语音服务$/);

  globalThis.fetch = async () => new Response("not-json");
  await assert.rejects(testTTSConnection, /^Error: 语音连接测试返回无效$/);
});
