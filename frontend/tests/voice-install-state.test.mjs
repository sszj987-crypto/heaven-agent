import assert from "node:assert/strict";
import test from "node:test";

import { voiceInstallPresentation } from "../components/settings/voice-install-state.ts";
import { voiceProviderPresentation } from "../components/soul/voice-provider-state.ts";


test("only absent or failed voice components can start installation", () => {
  assert.equal(voiceInstallPresentation("not_installed").canInstall, true);
  assert.equal(voiceInstallPresentation("failed").canInstall, true);
  assert.equal(voiceInstallPresentation("installing").canInstall, false);
  assert.equal(voiceInstallPresentation("restart_required").canInstall, false);
  assert.equal(voiceInstallPresentation("installed").canInstall, false);
});


test("only a completed install asks the user to restart", () => {
  assert.equal(voiceInstallPresentation("restart_required").restartRequired, true);
  assert.equal(voiceInstallPresentation("installed").restartRequired, false);
});

test("voice timbre hides recording until the local component is ready", () => {
  for (const state of ["not_installed", "creating"]) {
    const view = voiceProviderPresentation({ provider: "local", state, has_reference: false });
    assert.equal(view.showUpload, false);
  }
  assert.equal(voiceProviderPresentation({ provider: "local", state: "no_voice", has_reference: false }).showUpload, true);
});
