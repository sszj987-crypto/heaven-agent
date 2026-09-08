import assert from "node:assert/strict";
import test from "node:test";

import { voiceInstallPresentation } from "../components/soul/voice-install-state.ts";
import { voiceProviderPresentation } from "../components/soul/voice-provider-state.ts";


test("only absent or failed voice components can start installation", () => {
  assert.equal(voiceInstallPresentation("not_installed").canInstall, true);
  assert.equal(voiceInstallPresentation("failed").canInstall, true);
  assert.equal(voiceInstallPresentation("installing").canInstall, false);
  assert.equal(voiceInstallPresentation("restart_required").canInstall, false);
  assert.equal(voiceInstallPresentation("installed").canInstall, false);
});


test("voice controls are available only after the backend starts installed", () => {
  assert.equal(voiceInstallPresentation("restart_required").showVoiceControls, false);
  assert.equal(voiceInstallPresentation("installed").showVoiceControls, true);
});

test("local provider preserves installation and restart gating", () => {
  for (const state of ["not_installed", "installing", "restart_required", "failed"]) {
    const view = voiceProviderPresentation({ provider: "local", state, has_reference: false });
    assert.equal(view.showInstaller, true);
    assert.equal(view.showUpload, false);
  }
  assert.equal(voiceProviderPresentation({ provider: "local", state: "no_voice", has_reference: false }).showUpload, true);
});
