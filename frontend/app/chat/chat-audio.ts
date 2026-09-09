import type { TTSSettings } from "@/lib/api";
import type { Message } from "./chat-state";

type AudioPatch = Pick<Message, "audioState" | "audioUrl" | "audioError">;
interface AudioDependencies {
  createAudio: (url: string) => HTMLAudioElement;
  createURL: (blob: Blob) => string;
  revokeURL: (url: string) => void;
}
type AudioParams = NonNullable<Message["audioParams"]>;

export interface ChatAudioCache {
  get(params: AudioParams): string | undefined;
  put(params: AudioParams, blob: Blob): string;
  findByText(text: string): { params: AudioParams; url: string } | undefined;
  configure(limit: number): void;
  dispose(): void;
}

const browserAudioDependencies: AudioDependencies = {
  createAudio: url => new Audio(url),
  createURL: blob => URL.createObjectURL(blob),
  revokeURL: url => URL.revokeObjectURL(url),
};

const cacheKey = (params: AudioParams) => `${params.text}\u0000${params.instructText}`;

export function createChatAudioCache(
  dependencies: Pick<AudioDependencies, "createURL" | "revokeURL"> = browserAudioDependencies,
  limit = 10,
): ChatAudioCache {
  const entries = new Map<string, { params: AudioParams; url: string }>();
  let maxEntries = limit;
  const trim = () => {
    while (entries.size > maxEntries) {
      const oldest = entries.entries().next().value as [string, { url: string }];
      entries.delete(oldest[0]);
      dependencies.revokeURL(oldest[1].url);
    }
  };
  return {
    get(params) {
      const key = cacheKey(params);
      const entry = entries.get(key);
      if (!entry) return undefined;
      entries.delete(key);
      entries.set(key, entry);
      return entry.url;
    },
    put(params, blob) {
      const key = cacheKey(params);
      const previous = entries.get(key);
      if (previous) dependencies.revokeURL(previous.url);
      const url = dependencies.createURL(blob);
      entries.delete(key);
      entries.set(key, { params, url });
      trim();
      return url;
    },
    findByText(text) {
      for (const [key, entry] of Array.from(entries.entries()).reverse()) {
        if (entry.params.text !== text) continue;
        entries.delete(key);
        entries.set(key, entry);
        return entry;
      }
      return undefined;
    },
    configure(nextLimit) {
      maxEntries = Math.max(0, Math.min(100, Math.floor(nextLimit)));
      trim();
    },
    dispose() {
      entries.forEach(entry => dependencies.revokeURL(entry.url));
      entries.clear();
    },
  };
}

// This cache intentionally outlives a chat page mount, so navigation does not
// invalidate audio that was already generated.
const sharedCache = createChatAudioCache();

export function configureChatAudioCache(limit: number): void {
  sharedCache.configure(limit);
}

export function getSharedChatAudioCache(): ChatAudioCache {
  return sharedCache;
}

export function findCachedChatAudio(text: string) {
  return sharedCache.findByText(text);
}

export function createChatAudioSession(callbacks: {
  fetch: (params: AudioParams, signal: AbortSignal) => Promise<Blob>;
  update: (id: string, patch: AudioPatch) => void;
}, dependencies: AudioDependencies = browserAudioDependencies, cache?: ChatAudioCache) {
  const ownedCache = cache === undefined;
  const audioCache = cache ?? createChatAudioCache(dependencies);
  const pending = new Map<string, Promise<string | undefined>>();
  const prepared = new Set<string>();
  const generations = new Set<AbortController>();
  let queue = Promise.resolve();
  let disposed = false;
  let playbackIntent = 0;
  let audio: HTMLAudioElement | null = null;

  const releasePlayer = () => {
    if (!audio) return;
    audio.onended = null;
    audio.onerror = null;
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    audio = null;
  };
  const stop = () => {
    playbackIntent++;
    for (const controller of generations) controller.abort();
    releasePlayer();
  };

  const load = (message: Message): Promise<string | undefined> => {
    const { id, audioParams } = message;
    if (disposed || !id || !audioParams) return Promise.resolve(undefined);
    const cached = audioCache.get(audioParams);
    if (cached) {
      callbacks.update(id, { audioState: "ready", audioUrl: cached, audioError: undefined });
      return Promise.resolve(cached);
    }
    const key = cacheKey(audioParams);
    const existing = pending.get(key);
    if (existing) return existing;
    callbacks.update(id, { audioState: "loading", audioError: undefined });
    // Local models share compute resources; do not start overlapping inference.
    const generation = new AbortController();
    generations.add(generation);
    const request = queue.then(async () => {
      if (disposed) return;
      try {
        const blob = await callbacks.fetch(audioParams, generation.signal);
        if (disposed || generation.signal.aborted) return;
        const url = audioCache.put(audioParams, blob);
        callbacks.update(id, { audioState: "ready", audioUrl: url, audioError: undefined });
        return url;
      } catch (error) {
        if (!disposed && !generation.signal.aborted) callbacks.update(id, {
          audioState: "error",
          audioError: error instanceof Error ? error.message : "语音准备失败，请重试",
        });
      }
    }).finally(() => {
      generations.delete(generation);
      pending.delete(key);
    });
    pending.set(key, request);
    queue = request.then(() => undefined);
    return request;
  };

  const play = async (message: Message) => {
    if (disposed || !message.id || !message.audioParams) return;
    prepared.add(message.id);
    const intent = ++playbackIntent;
    releasePlayer();
    const url = await load(message);
    if (disposed || intent !== playbackIntent || !url) return;
    const id = message.id;
    const failed = (error?: unknown) => {
      if (disposed || intent !== playbackIntent) return;
      releasePlayer();
      const blocked = error instanceof DOMException && error.name === "NotAllowedError";
      callbacks.update(id, {
        audioState: "error",
        audioError: blocked ? "语音已准备好，请点击播放" : "语音播放失败，请重试",
      });
    };
    try {
      const player = dependencies.createAudio(url);
      audio = player;
      player.onended = () => { if (audio === player) releasePlayer(); };
      player.onerror = () => failed();
      await player.play();
      if (!disposed && intent === playbackIntent && audio === player) {
        callbacks.update(id, { audioState: "ready", audioError: undefined });
      }
    } catch (error) { failed(error); }
  };

  return {
    async prepare(message: Message, settings: Pick<TTSSettings, "provider" | "auto_play">) {
      if (disposed || !message.id || !message.audioParams || prepared.has(message.id)
          || message.audioState === "ready") return;
      prepared.add(message.id);
      if (settings.auto_play === true) await play(message);
      else if (settings.provider === "local") await load(message);
    },
    play,
    stop,
    dispose() {
      disposed = true;
      stop();
      pending.clear();
      prepared.clear();
      if (ownedCache) audioCache.dispose();
    },
  };
}
