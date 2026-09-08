import type { TTSProvider, TTSSettingsUpdate } from "@/lib/api";

export interface TTSSettingsForm {
  provider: TTSProvider;
  base_url: string;
  model: string;
  api_key: string;
}

export function buildTTSUpdate(form: TTSSettingsForm, keyDirty: boolean): TTSSettingsUpdate {
  const minimax: TTSSettingsUpdate["minimax"] = {
    base_url: form.base_url,
    model: form.model,
  };
  if (keyDirty) minimax.api_key = form.api_key;
  return { provider: form.provider, minimax };
}

export function resetTTSFormAfterSave(form: TTSSettingsForm): {
  form: TTSSettingsForm;
  keyDirty: false;
} {
  return { form: { ...form, api_key: "" }, keyDirty: false };
}

export interface TTSConnectionStatus {
  revision: number;
  result: boolean | null;
  error: string | null;
}

export function isTTSFormLocked(saving: boolean): boolean {
  return saving;
}

export function invalidateTTSConnection(status: TTSConnectionStatus): TTSConnectionStatus {
  return { revision: status.revision + 1, result: null, error: null };
}

export function acceptTTSConnectionResult(
  status: TTSConnectionStatus,
  revision: number,
  result: boolean | null,
  error: string | null = null,
): TTSConnectionStatus {
  if (status.revision !== revision) return status;
  return { ...status, result, error };
}

export async function runTTSConnectionTest(
  revision: number,
  testConnection: () => Promise<boolean>,
  updateStatus: (update: (status: TTSConnectionStatus) => TTSConnectionStatus) => void,
): Promise<void> {
  try {
    const result = await testConnection();
    updateStatus(status => acceptTTSConnectionResult(status, revision, result));
  } catch (error) {
    const message = error instanceof Error ? error.message : "语音连接测试失败";
    updateStatus(status => acceptTTSConnectionResult(status, revision, null, message));
  }
}
