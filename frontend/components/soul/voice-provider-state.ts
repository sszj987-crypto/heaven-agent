import type { TTSProvider, VoiceStatus, VoiceInstallationStatus } from "@/lib/api";

export async function loadVoicePanelStatus(
  fetchStatus: () => Promise<VoiceStatus>,
  fetchInstallation: () => Promise<VoiceInstallationStatus>,
) {
  const status = await fetchStatus();
  const installation = status.provider === "local" ? await fetchInstallation() : null;
  return { status, installation };
}

// Poll serially only while creation is pending; disposal also invalidates in-flight reads.
export function pollVoiceCreation(callbacks: {
  fetchStatus: () => Promise<VoiceStatus>;
  onStatus: (status: VoiceStatus) => void;
  onError: (error: Error) => void;
}) {
  let disposed = false;
  let creating = true;
  let timer: ReturnType<typeof setTimeout>;
  const poll = async () => {
    try {
      const status = await callbacks.fetchStatus();
      if (disposed) return;
      creating = status.provider === "minimax" && status.state === "creating";
      callbacks.onStatus(status);
    } catch (error) {
      if (!disposed) callbacks.onError(error instanceof Error ? error : new Error("无法读取声音状态"));
    } finally {
      if (!disposed && creating) timer = setTimeout(poll, 1500);
    }
  };
  timer = setTimeout(poll, 1500);
  return () => { disposed = true; clearTimeout(timer); };
}

export function voiceProviderPresentation(status: {
  provider: TTSProvider;
  state: string;
  has_reference: boolean;
  preview_available?: boolean;
}) {
  const showInstaller = status.provider === "local"
    && ["not_installed", "installing", "restart_required", "failed"].includes(status.state);
  return {
    showInstaller,
    showUpload: !showInstaller && !["not_configured", "creating"].includes(status.state),
    ready: status.state === "ready" && status.has_reference,
    showPreview: status.provider === "minimax" && status.state === "ready"
      && status.has_reference && status.preview_available === true,
    canRetry: status.state === "failed",
  };
}
