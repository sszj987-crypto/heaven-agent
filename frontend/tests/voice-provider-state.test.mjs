import assert from "node:assert/strict";
import test from "node:test";
import { voiceProviderPresentation, loadVoicePanelStatus, pollVoiceCreation } from "../components/soul/voice-provider-state.ts";

test("MiniMax never shows the local installer, even without local packages", () => {
  for (const state of ["no_voice", "failed", "not_installed", "ready"]) {
    const view = voiceProviderPresentation({ provider: "minimax", state, has_reference: state === "ready" });
    assert.equal(view.showInstaller, false);
    assert.equal(view.showUpload, true);
    assert.equal(view.ready, state === "ready");
    assert.equal(view.canRetry, state === "failed");
  }
});


test("persisted cloud preview visibility is restored from provider status", () => {
  const cloud = voiceProviderPresentation({
    provider: "minimax", state: "ready", has_reference: true, preview_available: true,
  });
  const local = voiceProviderPresentation({
    provider: "local", state: "ready", has_reference: true, preview_available: true,
  });

  assert.equal(cloud.showPreview, true);
  assert.equal(local.showPreview, false);
  assert.equal(voiceProviderPresentation({
    provider: "minimax", state: "ready", has_reference: true, preview_available: false,
  }).showPreview, false);
  assert.equal(voiceProviderPresentation({
    provider: "minimax", state: "creating", has_reference: true, preview_available: true,
  }).showPreview, false);
});

test("unconfigured or creating MiniMax cannot submit another sample", () => {
  for (const state of ["not_configured", "creating"]) {
    assert.equal(voiceProviderPresentation({ provider: "minimax", state, has_reference: false }).showUpload, false);
  }
});

test("local missing package shows installer and hides upload", () => {
  const view = voiceProviderPresentation({ provider: "local", state: "not_installed", has_reference: false });
  assert.equal(view.showInstaller, true);
  assert.equal(view.showUpload, false);
});

test("status loading asks provider first and never checks local installation for cloud", async () => {
  const calls = [];
  const cloud = { provider: "minimax", state: "no_voice", has_reference: false };
  const result = await loadVoicePanelStatus(async () => { calls.push("provider"); return cloud; }, async () => { throw Error("local installer must not run"); });
  assert.deepEqual(result, { status: cloud, installation: null });
  const local = { provider: "local", state: "not_installed", has_reference: false };
  const installation = { state: "installing", message: "downloading" };
  assert.deepEqual(await loadVoicePanelStatus(async () => { calls.push("provider"); return local; }, async () => { calls.push("installation"); return installation; }), { status: local, installation });
  assert.deepEqual(calls, ["provider", "provider", "installation"]);
});

test("cloud creation polling reaches ready or failed and stops polling terminal states", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  for (const terminal of ["ready", "failed"]) {
    let calls = 0;
    const received = [];
    const dispose = pollVoiceCreation({
      fetchStatus: async () => ({ provider: "minimax", state: ++calls === 1 ? "creating" : terminal, has_reference: terminal === "ready", preview_available: terminal === "ready", supports_instruction: false, message: terminal }),
      onStatus: status => received.push(status), onError: assert.fail,
    });
    t.mock.timers.tick(1500); await new Promise(resolve => setImmediate(resolve));
    assert.equal(received[0].state, "creating");
    t.mock.timers.tick(1500); await new Promise(resolve => setImmediate(resolve));
    assert.equal(received[1].state, terminal);
    const view = voiceProviderPresentation(received[1]);
    assert.equal(view.showUpload, true);
    assert.equal(view.ready, terminal === "ready");
    assert.equal(view.showPreview, terminal === "ready");
    assert.equal(view.canRetry, terminal === "failed");
    t.mock.timers.tick(15000); await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls, 2);
    dispose();
  }
});

test("cloud polling retries transient errors and cleanup ignores late responses", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let resolve;
  let calls = 0;
  const errors = [];
  const received = [];
  const dispose = pollVoiceCreation({
    fetchStatus: async () => { if (++calls === 1) throw Error("temporary"); return new Promise(done => { resolve = done; }); },
    onStatus: status => received.push(status), onError: error => errors.push(error.message),
  });
  t.mock.timers.tick(1500); await new Promise(done => setImmediate(done));
  assert.deepEqual(errors, ["temporary"]);
  t.mock.timers.tick(1500); await new Promise(done => setImmediate(done));
  dispose(); resolve({ provider: "minimax", state: "ready" }); await new Promise(done => setImmediate(done));
  t.mock.timers.tick(15000);
  assert.equal(calls, 2);
  assert.deepEqual(received, []);
});

test("disposing cloud polling before its first tick cancels the timer", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dispose = pollVoiceCreation({ fetchStatus: assert.fail, onStatus: assert.fail, onError: assert.fail });
  dispose(); t.mock.timers.tick(15000);
});
