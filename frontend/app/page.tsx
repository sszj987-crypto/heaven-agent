import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-col items-center justify-center flex-1 px-6 text-center">
      <h1 className="text-4xl font-light tracking-wider mb-4">VoiceFromHeaven</h1>
      <p className="text-lg text-white/40 mb-12">让思念有回响</p>

      <div className="flex gap-4">
        <Link
          href="/chat"
          className="px-8 py-3 rounded-full bg-white/10 hover:bg-white/20 transition-colors text-white/80"
        >
          开始对话
        </Link>
        <Link
          href="/soul"
          className="px-8 py-3 rounded-full border border-white/20 hover:border-white/40 transition-colors text-white/60"
        >
          灵魂档案
        </Link>
      </div>
    </div>
  );
}
