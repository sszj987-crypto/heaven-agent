import assert from "node:assert/strict";
import test from "node:test";

import {
  cancelChatRun,
  createChatRun,
  createVoiceChatRun,
  fetchChatRun,
  fetchHistory,
} from "../lib/api.ts";


const activeRun = {
  run_id: "chat_123",
  response_id: "reply_123",
  status: "running",
  user_message: "你好",
  response_text: "正在回",
  instruct_text: "自然地说",
  has_voice: true,
  used_memories: [],
  safety_state: "normal",
  timing: { first_response_ms: 50, total_response_ms: 0 },
  revision: 3,
  error: null,
};


test("chat generation starts as a server-owned run and can be polled", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push([String(url), init]);
    if (init?.method === "POST") return Response.json({ run_id: "chat_123" }, { status: 202 });
    return Response.json(activeRun);
  });

  assert.equal(await createChatRun("你好"), "chat_123");
  const run = await fetchChatRun("chat_123");

  assert.equal(calls[0][1]?.method, "POST");
  assert.deepEqual(JSON.parse(calls[0][1]?.body), { message: "你好" });
  assert.match(calls[1][0], /\/chat\/runs\/chat_123$/);
  assert.equal(run.status, "running");
  assert.equal(run.responseText, "正在回");
  assert.deepEqual(run.audioParams, { text: "正在回", instructText: "自然地说" });
});


test("history exposes an active run so a remounted page can resume it", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({
    messages: [{ role: "user", content: "上一轮" }],
    active_run: activeRun,
  }));

  const history = await fetchHistory();

  assert.deepEqual(history.messages, [{ role: "user", content: "上一轮" }]);
  assert.equal(history.activeRun?.runId, "chat_123");
  assert.equal(history.activeRun?.userMessage, "你好");
});


test("only an explicit stop sends cancellation to the background run", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push([String(url), init]);
    return new Response(null, { status: 204 });
  });

  await cancelChatRun("chat/with spaces");

  assert.match(calls[0][0], /\/chat\/runs\/chat%2Fwith%20spaces$/);
  assert.equal(calls[0][1]?.method, "DELETE");
});


test("voice upload returns after transcription with a background run id", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push([String(url), init]);
    return Response.json({ run_id: "chat_voice", transcript: "语音转写" }, { status: 202 });
  });

  const accepted = await createVoiceChatRun(new Blob(["voice"], { type: "audio/wav" }));

  assert.deepEqual(accepted, { runId: "chat_voice", transcript: "语音转写" });
  assert.match(calls[0][0], /\/chat\/voice\/runs$/);
  assert.equal(calls[0][1]?.method, "POST");
  assert.equal(calls[0][1]?.body.get("audio").type, "audio/wav");
});
