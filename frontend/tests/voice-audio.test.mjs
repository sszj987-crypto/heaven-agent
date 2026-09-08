import assert from "node:assert/strict";
import test from "node:test";
import { cloudAudioFileError, encodeMonoWav, selectRecordingMimeType, createVoiceRecording, createVoicePreview } from "../components/soul/voice-audio.ts";

test("cloud file validation accepts actual supported extensions without disguising WebM", () => {
  for (const [name, type] of [["a.WAV", "audio/wav"], ["a.mp3", "audio/mpeg"], ["a.m4a", "audio/mp4"], ["a.mp3", ""]]) {
    assert.equal(cloudAudioFileError(new File(["audio"], name, { type })), null);
  }
  for (const [name, type] of [["a.webm", "audio/webm"], ["a.wav", "audio/webm"], ["a.ogg", "audio/ogg"]]) {
    assert.match(cloudAudioFileError(new File(["audio"], name, { type })), /WAV.*MP3.*M4A/);
  }
  assert.match(cloudAudioFileError(new File([], "empty.wav")), /为空/);
});

test("WAV encoder writes mono PCM16 header, downmixes channels, and clamps samples", async () => {
  const blob = encodeMonoWav({ sampleRate: 24000, length: 4, numberOfChannels: 2,
    getChannelData: i => new Float32Array(i ? [1, -1, 0, 2] : [1, -1, 1, 2]) });
  assert.equal(blob.type, "audio/wav");
  const bytes = await blob.arrayBuffer();
  const view = new DataView(bytes);
  assert.equal(bytes.byteLength, 52);
  assert.equal(new TextDecoder().decode(bytes.slice(0, 4)), "RIFF");
  assert.equal(new TextDecoder().decode(bytes.slice(8, 12)), "WAVE");
  assert.equal(view.getUint16(20, true), 1);
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(24, true), 24000);
  assert.equal(view.getUint32(28, true), 48000);
  assert.equal(view.getUint16(34, true), 16);
  assert.deepEqual([44, 46, 48, 50].map(offset => view.getInt16(offset, true)), [32767, -32768, 16383, 32767]);
});

test("recorder MIME is negotiated with fallback to browser default", () => {
  assert.equal(selectRecordingMimeType(type => type === "audio/mp4"), "audio/mp4");
  assert.equal(selectRecordingMimeType(() => false), undefined);
});

function recordingHarness({ media, decode, failStart = false, cloud = true } = {}) {
  const events = [];
  const stream = { getTracks: () => [{ stop: () => events.push("track-stop") }] };
  let recorder;
  const session = createVoiceRecording({ cloud,
    onRecording: value => events.push(["recording", value]),
    onSample: blob => events.push(blob), onError: error => events.push(error.message),
  }, {
    getUserMedia: () => media || Promise.resolve(stream),
    isTypeSupported: type => type === "audio/mp4",
    createRecorder: (_stream, options) => {
      assert.equal(options.mimeType, "audio/mp4");
      recorder = { state: "inactive", mimeType: "audio/mp4", start() { if (failStart) throw Error("start failed"); this.state = "recording"; },
        stop() { this.state = "inactive"; this.ondataavailable?.({ data: new Blob(["encoded"], { type: "audio/mp4" }) }); this.onstop?.(); } };
      return recorder;
    },
    createAudioContext: () => ({ decodeAudioData: () => decode || Promise.resolve({ sampleRate: 24000, length: 1, numberOfChannels: 1, getChannelData: () => new Float32Array([1]) }), close: async () => events.push("context-close") }),
  });
  return { session, events, stream, recorder: () => recorder };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test("cloud recording becomes WAV, while local keeps negotiated native bytes", async () => {
  for (const cloud of [true, false]) {
    const { session, events } = recordingHarness({ cloud });
    await session.start(); session.stop(); await tick();
    const blob = events.find(value => value instanceof Blob);
    assert.equal(blob.type, cloud ? "audio/wav" : "audio/mp4");
    assert.ok(events.includes("track-stop"));
    assert.equal(events.includes("context-close"), cloud);
    session.dispose();
  }
});

test("recording stops an active preview before requesting microphone permission", async () => {
  const events = [];
  const audio = { src: "", play: async () => events.push("play"), pause: () => events.push("pause"), removeAttribute: () => events.push("remove-src"), load: () => {} };
  const preview = createVoicePreview({ fetch: async () => new Blob(["sound"]), onError: assert.fail, onBusy: () => {} }, {
    createAudio: () => audio, createURL: () => "blob:preview", revokeURL: url => events.push(url),
  });
  await preview.play();
  const recording = createVoiceRecording({ cloud: true, stopPlayback: () => preview.dispose(), onRecording: () => {}, onSample: assert.fail, onError: assert.fail }, {
    getUserMedia: async () => { events.push("microphone"); return { getTracks: () => [] }; },
    isTypeSupported: () => false,
    createRecorder: () => ({ state: "inactive", start() {}, stop() {} }),
    createAudioContext: assert.fail,
  });
  await recording.start();
  assert.deepEqual(events, ["play", "pause", "remove-src", "blob:preview", "microphone"]);
  recording.dispose();
});

test("unmount during recording stops tracks and never submits", async () => {
  const { session, events } = recordingHarness();
  await session.start(); session.dispose(); await tick();
  assert.ok(events.includes("track-stop"));
  assert.equal(events.some(value => value instanceof Blob), false);
});

test("recorder error stops the recorder and stream without submitting partial audio", async () => {
  const h = recordingHarness();
  await h.session.start(); h.recorder().onerror(); await tick();
  assert.equal(h.recorder().state, "inactive");
  assert.equal(h.recorder().ondataavailable, null);
  assert.ok(h.events.includes("track-stop"));
  assert.equal(h.events.some(value => value instanceof Blob), false);
});

test("late microphone permission after unmount immediately releases the stream", async () => {
  let resolve;
  const h = recordingHarness({ media: new Promise(done => { resolve = done; }) });
  const pending = h.session.start(); h.session.dispose(); resolve(h.stream); await pending;
  assert.deepEqual(h.events, ["track-stop"]);
});

test("late decoding after unmount never submits and context is closed once", async () => {
  let resolve;
  const h = recordingHarness({ decode: new Promise(done => { resolve = done; }) });
  await h.session.start(); h.session.stop(); await tick(); h.session.dispose();
  resolve({ sampleRate: 24000, length: 1, numberOfChannels: 1, getChannelData: () => new Float32Array([1]) });
  await tick();
  assert.equal(h.events.filter(value => value === "context-close").length, 1);
  assert.equal(h.events.some(value => value instanceof Blob), false);
});

test("recorder startup and decoding failures clean up and report useful errors", async () => {
  const startup = recordingHarness({ failStart: true });
  await startup.session.start();
  assert.ok(startup.events.includes("track-stop"));
  assert.ok(startup.events.includes("start failed"));
  const decoding = recordingHarness({ decode: Promise.resolve().then(() => { throw Error("decode failed"); }) });
  await decoding.session.start(); decoding.session.stop(); await tick();
  assert.ok(decoding.events.includes("context-close"));
  assert.ok(decoding.events.includes("decode failed"));
});

test("preview only plays explicitly and releases audio/URL on ended, failure and disposal", async () => {
  for (const mode of ["ended", "reject", "error", "dispose"]) {
    const events = [];
    const audio = { src: "", play: async () => { events.push("play"); if (mode === "reject") throw Error("blocked"); }, pause: () => events.push("pause"), removeAttribute: () => events.push("remove-src"), load: () => {} };
    const preview = createVoicePreview({ fetch: async () => new Blob(["sound"]), onError: error => events.push(error.message), onBusy: () => {} }, {
      createAudio: () => audio, createURL: () => "blob:preview", revokeURL: url => events.push(url),
    });
    assert.deepEqual(events, []);
    await preview.play();
    if (mode === "ended") audio.onended();
    if (mode === "error") audio.onerror();
    preview.dispose();
    assert.equal(events.filter(value => value === "blob:preview").length, 1);
    assert.ok(events.includes("pause"));
    assert.ok(events.includes("remove-src"));
    if (mode === "reject") assert.ok(events.includes("blocked"));
    if (mode === "error") assert.ok(events.includes("试听播放失败，请重试"));
  }
});

test("preview fetch errors and late fetch completion after disposal never play", async () => {
  let resolve;
  const errors = [];
  const preview = createVoicePreview({ fetch: () => new Promise(done => { resolve = done; }), onError: e => errors.push(e.message), onBusy: () => {} }, {
    createAudio: () => { throw Error("must not play"); }, createURL: () => { throw Error("must not allocate"); }, revokeURL: () => {},
  });
  const pending = preview.play(); preview.dispose(); resolve(new Blob(["sound"])); await pending;
  assert.deepEqual(errors, []);
  const failed = createVoicePreview({ fetch: async () => { throw Error("missing preview"); }, onError: e => errors.push(e.message), onBusy: () => {} });
  await failed.play(); assert.deepEqual(errors, ["missing preview"]);
});
