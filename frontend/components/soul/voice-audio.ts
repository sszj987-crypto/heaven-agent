export function cloudAudioFileError(file: File): string | null {
  if (!file.size) return "音频数据为空";
  const mime = file.type.split(";")[0].toLowerCase();
  if (!/\.(wav|mp3|m4a)$/i.test(file.name)
    || (mime && !["audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave", "audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "application/octet-stream"].includes(mime))) {
    return "MiniMax 仅支持 WAV、MP3、M4A 文件，请转换格式后上传";
  }
  return null;
}

export function encodeMonoWav(audio: Pick<AudioBuffer, "sampleRate" | "length" | "numberOfChannels" | "getChannelData">): Blob {
  const buffer = new ArrayBuffer(44 + audio.length * 2);
  const view = new DataView(buffer);
  const write = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  write(0, "RIFF"); view.setUint32(4, buffer.byteLength - 8, true); write(8, "WAVE");
  write(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, audio.sampleRate, true);
  view.setUint32(28, audio.sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  write(36, "data"); view.setUint32(40, audio.length * 2, true);
  const channels = Array.from({ length: audio.numberOfChannels }, (_, i) => audio.getChannelData(i));
  for (let i = 0; i < audio.length; i++) {
    const sample = Math.max(-1, Math.min(1, channels.reduce((sum, channel) => sum + channel[i], 0) / channels.length));
    view.setInt16(44 + i * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export function selectRecordingMimeType(supported: (mime: string) => boolean): string | undefined {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find(supported);
}

interface RecordingDependencies {
  getUserMedia: () => Promise<MediaStream>;
  isTypeSupported: (mime: string) => boolean;
  createRecorder: (stream: MediaStream, options: MediaRecorderOptions) => MediaRecorder;
  createAudioContext: () => AudioContext;
}

// Owns microphone and decoding resources for one recording, including late browser promises.
export function createVoiceRecording(callbacks: {
  cloud: boolean;
  stopPlayback?: () => void;
  onRecording: (recording: boolean) => void;
  onSample: (blob: Blob) => void;
  onError: (error: Error) => void;
}, dependencies: RecordingDependencies = {
  getUserMedia: () => navigator.mediaDevices.getUserMedia({ audio: true }),
  isTypeSupported: mime => MediaRecorder.isTypeSupported(mime),
  createRecorder: (stream, options) => new MediaRecorder(stream, options),
  createAudioContext: () => new AudioContext(),
}) {
  let disposed = false;
  let stream: MediaStream | null = null;
  let recorder: MediaRecorder | null = null;
  let context: AudioContext | null = null;
  const chunks: Blob[] = [];
  const releaseStream = () => { stream?.getTracks().forEach(track => track.stop()); stream = null; };
  const closeContext = () => {
    const active = context; context = null;
    if (active) void active.close().catch(() => undefined);
  };
  const report = (error: unknown) => {
    if (!disposed) callbacks.onError(error instanceof Error ? error : new Error("录音处理失败，请重试"));
  };
  const complete = async () => {
    releaseStream();
    if (disposed || !recorder) return;
    callbacks.onRecording(false);
    try {
      const blob = new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || "application/octet-stream" });
      if (!blob.size) throw new Error("未录到声音，请重试");
      if (!callbacks.cloud) { callbacks.onSample(blob); return; }
      context = dependencies.createAudioContext();
      const active = context;
      const bytes = await blob.arrayBuffer();
      if (disposed) return;
      const decoded = await active.decodeAudioData(bytes);
      if (!disposed) callbacks.onSample(encodeMonoWav(decoded));
    } catch (error) { report(error); }
    finally { closeContext(); }
  };
  return {
    async start() {
      try {
        callbacks.stopPlayback?.();
        const acquired = await dependencies.getUserMedia();
        if (disposed) { acquired.getTracks().forEach(track => track.stop()); return; }
        stream = acquired;
        const mimeType = selectRecordingMimeType(dependencies.isTypeSupported);
        recorder = dependencies.createRecorder(stream, mimeType ? { mimeType } : {});
        recorder.ondataavailable = event => { if (!disposed && event.data.size) chunks.push(event.data); };
        recorder.onstop = () => { void complete(); };
        recorder.onerror = () => {
          if (recorder) {
            recorder.onstop = null; recorder.ondataavailable = null; recorder.onerror = null;
            if (recorder.state !== "inactive") recorder.stop();
          }
          releaseStream();
          closeContext();
          if (!disposed) callbacks.onRecording(false);
          report(new Error("录音失败，请检查麦克风后重试"));
        };
        recorder.start();
        callbacks.onRecording(true);
      } catch (error) { releaseStream(); report(error); }
    },
    stop() { if (recorder?.state === "recording") recorder.stop(); },
    dispose() {
      disposed = true;
      if (recorder) {
        recorder.ondataavailable = null; recorder.onstop = null; recorder.onerror = null;
        if (recorder.state !== "inactive") recorder.stop();
      }
      releaseStream(); closeContext();
    },
  };
}

interface PreviewDependencies {
  createAudio: () => HTMLAudioElement;
  createURL: (blob: Blob) => string;
  revokeURL: (url: string) => void;
}

export function createVoicePreview(callbacks: {
  fetch: () => Promise<Blob>;
  onError: (error: Error) => void;
  onBusy: (busy: boolean) => void;
}, dependencies: PreviewDependencies = {
  createAudio: () => new Audio(), createURL: blob => URL.createObjectURL(blob), revokeURL: url => URL.revokeObjectURL(url),
}) {
  let disposed = false;
  let generation = 0;
  let audio: HTMLAudioElement | null = null;
  let url: string | null = null;
  const release = () => {
    if (audio) { audio.onended = null; audio.onerror = null; audio.pause(); audio.removeAttribute("src"); audio.load(); audio = null; }
    if (url) { dependencies.revokeURL(url); url = null; }
  };
  return {
    async play() {
      if (disposed) return;
      const current = ++generation;
      release(); callbacks.onBusy(true);
      try {
        const blob = await callbacks.fetch();
        if (disposed || generation !== current) return;
        audio = dependencies.createAudio(); url = dependencies.createURL(blob); audio.src = url;
        const finish = () => { release(); if (!disposed) callbacks.onBusy(false); };
        audio.onended = finish;
        audio.onerror = () => { finish(); if (!disposed) callbacks.onError(new Error("试听播放失败，请重试")); };
        await audio.play();
      } catch (error) {
        if (disposed || generation !== current) return;
        release(); callbacks.onBusy(false);
        callbacks.onError(error instanceof Error ? error : new Error("试听播放失败，请重试"));
      }
    },
    dispose() { disposed = true; generation++; release(); },
  };
}
