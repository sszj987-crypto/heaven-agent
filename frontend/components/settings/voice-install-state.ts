import type { VoiceInstallState } from "@/lib/api";

export function voiceInstallPresentation(state: VoiceInstallState) {
  return {
    canInstall: state === "not_installed" || state === "failed",
    installing: state === "installing",
    restartRequired: state === "restart_required",
  };
}
