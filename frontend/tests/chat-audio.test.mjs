import assert from "node:assert/strict";
import test from "node:test";

import { createChatAudioCache, createChatAudioSession } from "../app/chat/chat-audio.ts";
const message = (id = "reply") => ({ id, role: "assistant", content: "你好", audioParams: { text: "你好", instructText: "温柔地说" }, audioState: "idle" });
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function harness(fetch, playError) {
  const events = [], states = new Map(), audios = [];
  const session = createChatAudioSession({
    fetch: async (params, signal) => { events.push(["fetch", params]); return fetch ? fetch(signal) : new Blob(["audio"]); },
    update: (id, patch) => states.set(id, { ...states.get(id), ...patch }),
  }, {
    createURL: () => { const url = `blob:${events.length}`; events.push(["url", url]); return url; },
    revokeURL: url => events.push(["revoke", url]),
    createAudio: url => {
      const audio = { onended: null, onerror: null,
        play: async () => { events.push(["play", url]); if (playError) throw playError; },
        pause: () => events.push(["pause", url]), removeAttribute() {}, load() {},
      };
      audios.push(audio);
      return audio;
    },
  });
  return { session, events, states, audios, count: type => events.filter(event => event[0] === type).length };
}

test("local replies generate before clicking and replay uses cached audio", async () => {
  const h = harness();
  await h.session.prepare(message(), { provider: "local", auto_play: false });
  assert.equal(h.states.get("reply").audioState, "ready");
  assert.equal(h.count("fetch"), 1);
  assert.equal(h.count("play"), 0);
  await h.session.play(message());
  await h.session.play(message());
  assert.equal(h.count("fetch"), 1);
  assert.equal(h.count("play"), 2);
  h.session.dispose();
  assert.equal(h.count("revoke"), 1);
});

test("a shared cache survives a chat page session and evicts by configured size", async () => {
  const events = [];
  const cache = createChatAudioCache({
    createURL: blob => `blob:${blob.size}:${events.length}`,
    revokeURL: url => events.push(["revoke", url]),
  }, 1);
  const dependencies = {
    createURL: blob => `unused:${blob.size}`,
    revokeURL: () => {},
    createAudio: () => ({ play: async () => {}, pause() {}, removeAttribute() {}, load() {} }),
  };
  const first = createChatAudioSession({ fetch: async () => new Blob(["one"]), update: () => {} }, dependencies, cache);
  await first.play(message());
  first.dispose();
  const second = createChatAudioSession({
    fetch: async () => { throw Error("should use cached audio"); }, update: () => {},
  }, dependencies, cache);
  await second.play(message());
  cache.configure(0);
  assert.equal(events.filter(event => event[0] === "revoke").length, 1);
  second.dispose();
});

test("cloud stays on demand by default; enabling autoplay prepares and plays either provider", async () => {
  const manual = harness();
  await manual.session.prepare(message(), { provider: "minimax", auto_play: false });
  assert.equal(manual.count("fetch"), 0);
  await manual.session.play(message());
  assert.equal(manual.count("play"), 1);
  manual.session.dispose();
  for (const provider of ["local", "minimax"]) {
    const h = harness();
    await h.session.prepare(message(), { provider, auto_play: true });
    await h.session.prepare(message(), { provider, auto_play: true });
    assert.equal(h.count("fetch"), 1);
    assert.equal(h.count("play"), 1);
    h.session.dispose();
  }
});

test("history and voiceless replies never generate or autoplay", async () => {
  const h = harness();
  for (const msg of [{ role: "assistant", content: "历史" }, { id: "silent", role: "assistant", content: "无音色" }]) {
    await h.session.prepare(msg, { provider: "local", auto_play: true });
  }
  assert.equal(h.count("fetch"), 0);
  assert.equal(h.count("play"), 0);
});

test("late settings loading does not replay a message already played manually", async () => {
  const h = harness();
  await h.session.play(message());
  await h.session.prepare(message(), { provider: "local", auto_play: true });
  assert.equal(h.count("play"), 1);
  h.session.dispose();
});

test("clicking while preparation is pending shares the request and plays only once", async () => {
  const result = deferred();
  const h = harness(() => result.promise);
  const prepared = h.session.prepare(message(), { provider: "local", auto_play: true });
  await tick();
  assert.equal(h.states.get("reply").audioState, "loading");
  const played = h.session.play(message());
  result.resolve(new Blob(["audio"]));
  await Promise.all([prepared, played]);
  assert.equal(h.count("fetch"), 1);
  assert.equal(h.count("play"), 1);
  h.session.dispose();
});

test("failed preparation does not loop and explicit playback retries", async () => {
  let fails = true;
  const h = harness(async () => { if (fails) throw Error("语音准备失败"); return new Blob(["audio"]); });
  await h.session.prepare(message(), { provider: "local", auto_play: false });
  assert.equal(h.states.get("reply").audioState, "error");
  assert.match(h.states.get("reply").audioError, /语音准备失败/);
  await h.session.prepare(message(), { provider: "local", auto_play: false });
  assert.equal(h.count("fetch"), 1);
  fails = false;
  await h.session.play(message());
  assert.equal(h.states.get("reply").audioState, "ready");
  assert.equal(h.states.get("reply").audioError, undefined);
  assert.equal(h.count("fetch"), 2);
  h.session.dispose();
});

test("autoplay blocked by browser keeps cached audio for manual retry", async () => {
  const h = harness(undefined, new DOMException("blocked", "NotAllowedError"));
  await h.session.prepare(message(), { provider: "local", auto_play: true });
  assert.match(h.states.get("reply").audioError, /点击播放/);
  assert.ok(h.states.get("reply").audioUrl);
  await h.session.play(message());
  assert.equal(h.count("fetch"), 1);
  h.session.dispose();
});

test("dispose aborts work and suppresses late URLs, state updates and playback", async () => {
  const result = deferred();
  let signal;
  const h = harness(value => { signal = value; return result.promise; });
  const pending = h.session.prepare(message(), { provider: "local", auto_play: true });
  await tick();
  h.session.dispose();
  assert.equal(signal.aborted, true);
  result.resolve(new Blob(["late"]));
  await pending;
  assert.equal(h.count("url"), 0);
  assert.equal(h.count("play"), 0);
  assert.equal(h.states.get("reply").audioState, "loading");
});

test("newer playback intent and recording stop prevent late autoplay", async () => {
  for (const stop of [false, true]) {
    const result = deferred();
    const h = harness(() => result.promise);
    const old = h.session.prepare(message("old"), { provider: "local", auto_play: true });
    await tick();
    const next = stop ? h.session.stop() : h.session.prepare(message("new"), { provider: "local", auto_play: true });
    result.resolve(new Blob(["audio"]));
    await Promise.all([old, next]);
    assert.equal(h.count("play"), stop ? 0 : 1);
    h.session.dispose();
  }
});

test("local generation is serialized to avoid running the model concurrently", async () => {
  const result = deferred();
  const h = harness(() => result.promise);
  const first = h.session.prepare({ ...message("first"), audioParams: { text: "第一条", instructText: "温柔地说" } }, { provider: "local", auto_play: false });
  const second = h.session.prepare({ ...message("second"), audioParams: { text: "第二条", instructText: "温柔地说" } }, { provider: "local", auto_play: false });
  await tick();
  assert.equal(h.count("fetch"), 1);
  result.resolve(new Blob(["audio"]));
  await Promise.all([first, second]);
  assert.equal(h.count("fetch"), 2);
  h.session.dispose();
});
