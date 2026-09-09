import assert from "node:assert/strict";
import test from "node:test";
import { renderComponent } from "./helpers/render-component.mjs";

test("navigation exposes About and marks only the current destination", () => {
  for (const pathname of ["/", "/chat", "/soul", "/settings", "/about"]) {
    const html = renderComponent("app/layout.tsx", { children: "content" }, pathname);
    const links = html.match(/<a\b[^>]*>.*?<\/a>/gs) ?? [];
    assert.ok(links.some(link => /href="\/about"/.test(link)), "About must be reachable from every page");
    const current = links.filter(link => /aria-current="page"/.test(link));
    assert.equal(current.length, 1, `one selected destination on ${pathname}`);
    assert.ok(current[0].includes(`href="${pathname}"`));
  }
});

const tts = {
  provider: "minimax",
  minimax: { base_url: "https://example.test/speech", model: "saved-speech-model", api_key_configured: true },
};

test("voice autoplay is off for old settings and reflects a saved preference", () => {
  for (const enabled of [undefined, false, true]) {
    const html = renderComponent("components/settings/TTSSettingsSection.tsx#TTSSettingsSection", {
      tts: { ...tts, auto_play: enabled }, onSaved: async () => {},
    });
    assert.match(html, /自动播放语音/);
    const toggle = html.match(/<input[^>]*type="checkbox"[^>]*>/)?.[0];
    assert.ok(toggle);
    assert.equal(toggle.includes("checked"), enabled === true);
  }
});

test("MiniMax keeps saved advanced values in a closed disclosure and its key outside it", () => {
  const html = renderComponent("components/settings/TTSSettingsSection.tsx#TTSSettingsSection", { tts, onSaved: async () => {} });
  const advanced = html.match(/<details\b[^>]*>.*?<\/details>/s)?.[0];
  assert.ok(advanced, "advanced speech settings must be collapsible");
  assert.doesNotMatch(advanced, /^<details[^>]*\bopen[= >]/);
  assert.match(advanced, /value="https:\/\/example.test\/speech"/);
  assert.match(advanced, /value="saved-speech-model"/);
  assert.doesNotMatch(advanced, /type="password"/);
  assert.match(html, /MiniMax 语音密钥/);
  assert.match(html, /aria-pressed="true"[^>]*>MiniMax/);
});

test("local speech does not render cloud credentials or an installer in Settings", () => {
  const html = renderComponent("components/settings/TTSSettingsSection.tsx#TTSSettingsSection", {
    tts: { ...tts, provider: "local" }, onSaved: async () => {},
  });
  assert.doesNotMatch(html, /type="password"/);
  assert.match(html, /aria-pressed="true"[^>]*>本地/);
  assert.doesNotMatch(html, /<button[^>]*>安装语音组件/);
});
