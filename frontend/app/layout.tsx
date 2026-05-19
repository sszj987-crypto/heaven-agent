import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "VoiceFromHeaven - 让思念有回响",
  description: "为失去挚爱之人提供跨越生死对话的 AI Agent",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen flex flex-col">
        <nav className="flex items-center gap-6 px-6 py-4 border-b border-white/10">
          <Link href="/" className="text-lg font-semibold tracking-wide text-white/80 hover:text-white transition-colors">
            VoiceFromHeaven
          </Link>
          <Link href="/chat" className="text-sm text-white/50 hover:text-white/80 transition-colors">对话</Link>
          <Link href="/soul" className="text-sm text-white/50 hover:text-white/80 transition-colors">灵魂档案</Link>
          <Link href="/settings" className="text-sm text-white/50 hover:text-white/80 transition-colors">设置</Link>
        </nav>
        <main className="flex-1">{children}</main>
      </body>
    </html>
  );
}
