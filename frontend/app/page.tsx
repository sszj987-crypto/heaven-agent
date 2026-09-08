"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { completeOnboarding, fetchSystemStatus, type SystemStatus } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchSystemStatus()
      .then((result) => {
        if (result.onboarding.completed) router.replace("/chat");
        else setStatus(result);
      })
      .catch(() => setError("暂时无法连接本地服务，请确认启动脚本仍在运行。"));
  }, [router]);

  const finish = async () => {
    try {
      await completeOnboarding();
      router.push("/chat");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂时无法完成设置");
    }
  };

  if (!status && !error) {
    return <div className="flex flex-1 items-center justify-center text-sm text-stone-400">正在准备你的空间…</div>;
  }

  return (
    <div className="flex flex-1 items-center justify-center px-6 py-12">
      <div className="w-full max-w-2xl rounded-[2rem] border border-amber-100/10 bg-stone-900/70 p-8 shadow-2xl shadow-black/30 md:p-12">
        <p className="mb-3 text-xs tracking-[0.3em] text-amber-100/40">初次相识</p>
        <h1 className="text-3xl font-light tracking-wide text-stone-100">先留下那些值得被记住的事</h1>
        <p className="mt-4 max-w-xl leading-7 text-stone-400">
          这里生成的是基于你提供资料的 AI 人物模拟，内容可能不准确。你始终可以查看、修改或删除资料。
        </p>

        <ol className="mt-10 space-y-3">
          <SetupStep index="1" label="人物信息" done={Boolean(status?.onboarding.profile_ready)} href="/soul" />
          <SetupStep index="2" label="导入并确认记忆" done={Boolean(status?.onboarding.import_review_ready)} href="/soul" />
          <SetupStep index="3" label="创建声音（可稍后完成）" done={Boolean(status?.onboarding.voice_ready)} href="/soul" optional />
          <SetupStep index="4" label="开始对话" done={false} href="/chat" />
        </ol>

        {error && <p className="mt-6 rounded-xl bg-red-950/30 px-4 py-3 text-sm text-red-200/70">{error}</p>}

        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/soul" className="rounded-full bg-amber-100 px-6 py-2.5 text-sm text-stone-950 transition hover:bg-amber-50">
            继续完善档案
          </Link>
          {status?.onboarding.profile_ready && status.onboarding.import_review_ready && (
            <button onClick={finish} className="rounded-full border border-amber-100/20 px-6 py-2.5 text-sm text-stone-300 hover:border-amber-100/40">
              {status.onboarding.voice_ready ? "完成并开始对话" : "暂不创建声音，开始对话"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function SetupStep({ index, label, done, href, optional = false }: {
  index: string;
  label: string;
  done: boolean;
  href: string;
  optional?: boolean;
}) {
  return (
    <li>
      <Link href={href} className="flex items-center gap-4 rounded-2xl border border-white/5 bg-white/[0.025] px-4 py-3 hover:bg-white/[0.05]">
        <span className={`flex h-8 w-8 items-center justify-center rounded-full text-xs ${done ? "bg-emerald-900/50 text-emerald-200" : "bg-amber-100/10 text-amber-100/60"}`}>
          {done ? "✓" : index}
        </span>
        <span className="text-sm text-stone-300">{label}</span>
        {optional && <span className="ml-auto text-xs text-stone-600">可选</span>}
      </Link>
    </li>
  );
}
