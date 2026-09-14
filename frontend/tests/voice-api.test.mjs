import assert from "node:assert/strict";
import test from "node:test";
import {
  fetchVoiceDialect, fetchVoicePreview, fetchVoiceStatus, localReferenceCandidateAudioUrl,
  prepareLocalReferenceCandidates, selectLocalReferenceCandidate, uploadVoiceSample,
  updateVoiceDialect,
} from "../lib/api.ts";

test("dialect mode is fetched and saved through the voice settings API", async (t) => {
  const calls = [];
  const cantonese = {
    enabled: true, dialect_id: "cantonese", supports_voice_delivery: true,
    voice_delivery_message: "当前本地 CosyVoice 将使用自然粤语口音合成。",
    dialects: [{ id: "mandarin", label: "普通话", description: "默认" }, { id: "cantonese", label: "粤语", description: "繁体粤语口语" }],
  };
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push([String(url), init]);
    return Response.json(cantonese);
  });

  assert.deepEqual(await fetchVoiceDialect(), cantonese);
  assert.deepEqual(await updateVoiceDialect({ enabled: true, dialect_id: "cantonese" }), cantonese);
  assert.match(calls[0][0], /\/settings\/voice\/dialect$/);
  assert.equal(calls[1][1]?.method, "PUT");
  assert.deepEqual(JSON.parse(calls[1][1]?.body), { enabled: true, dialect_id: "cantonese" });
});

test("status restores saved preview availability without fetching or generating audio", async (t) => {
  const calls = [];
  const status = {
    provider: "minimax", state: "ready", has_reference: true,
    supports_instruction: true, message: "音色已就绪", preview_available: true,
  };
  t.mock.method(globalThis, "fetch", async url => {
    calls.push(String(url));
    return Response.json(status);
  });

  assert.deepEqual(await fetchVoiceStatus(), status);
  assert.equal(calls.length, 1);
  assert.match(calls[0], /\/settings\/voice\/status$/);
});

test("sample uploads preserve File names and MIME and return preview availability", async (t) => {
  const uploads = [];
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    uploads.push(init.body.get("audio"));
    return Response.json({ status: "ok", preview_available: true });
  });
  assert.equal((await uploadVoiceSample(new File(["sample"], "my-voice.MP3", { type: "audio/mpeg" }))).preview_available, true);
  await uploadVoiceSample(new Blob(["webm"], { type: "audio/webm;codecs=opus" }));
  await uploadVoiceSample(new Blob(["wav"], { type: "audio/wav" }));
  assert.deepEqual(uploads.map(file => [file.name, file.type]), [
    ["my-voice.MP3", "audio/mpeg"], ["reference.webm", "audio/webm;codecs=opus"], ["reference.wav", "audio/wav"],
  ]);
});

test("local reference clips are prepared, previewed by URL, and selected explicitly", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push([String(url), init?.method || "GET"]);
    if (String(url).endsWith("/candidates")) {
      assert.equal(init?.body.get("audio").name, "reference.wav");
      return Response.json({ candidates: [{ id: "clip 1", label: "候选片段 1", start_seconds: 0, duration_seconds: 10 }] });
    }
    return Response.json({ status: "ok", preview_available: false });
  });

  assert.deepEqual(await prepareLocalReferenceCandidates(new Blob(["wav"], { type: "audio/wav" })), [
    { id: "clip 1", label: "候选片段 1", start_seconds: 0, duration_seconds: 10 },
  ]);
  assert.match(localReferenceCandidateAudioUrl("clip 1"), /candidates\/clip%201\/audio$/);
  await selectLocalReferenceCandidate("clip 1");
  assert.deepEqual(calls.map(call => call[1]), ["POST", "POST"]);
  assert.match(calls[1][0], /candidates\/clip%201\/select$/);
});

test("preview is a GET with useful server errors and rejects empty audio", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, init) => {
    assert.match(String(url), /\/settings\/voice\/preview$/);
    assert.ok(!init?.method || init.method === "GET");
    return new Response("audio", { headers: { "content-type": "audio/mpeg" } });
  });
  assert.equal(await (await fetchVoicePreview()).text(), "audio");
  globalThis.fetch = async () => Response.json({ message: "试听不存在" }, { status: 404 });
  await assert.rejects(fetchVoicePreview, /试听不存在/);
  globalThis.fetch = async () => new Response("");
  await assert.rejects(fetchVoicePreview, /试听音频为空/);
});
