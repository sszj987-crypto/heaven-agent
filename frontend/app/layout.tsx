import type { Metadata } from "next";
import AppNavigation from "@/components/AppNavigation";
import "./globals.css";

export const metadata: Metadata = {
  title: "Heaven Agent - 让思念有回响",
  description: "本地优先、明确标识 AI 模拟的数字纪念对话体验",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="h-dvh flex flex-col overflow-hidden">
        <AppNavigation />
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</main>
      </body>
    </html>
  );
}
