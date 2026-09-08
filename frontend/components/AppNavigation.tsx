"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const destinations = [
  { href: "/chat", label: "对话" },
  { href: "/soul", label: "灵魂档案" },
  { href: "/settings", label: "设置" },
  { href: "/about", label: "关于" },
];

export default function AppNavigation() {
  const pathname = usePathname();

  return (
    <nav aria-label="主导航" className="app-navigation flex shrink-0 items-center gap-8 border-b border-amber-100/10 bg-stone-950/20 px-8 py-3 backdrop-blur">
      <Link href="/" aria-current={pathname === "/" ? "page" : undefined} className="shrink-0 text-lg font-semibold tracking-wide text-stone-200 transition-colors hover:text-white">
        Heaven Agent
      </Link>
      <div className="flex items-center gap-2">
        {destinations.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            aria-current={pathname === href ? "page" : undefined}
            className="rounded-lg px-4 py-2 text-sm text-stone-400 transition-colors hover:bg-white/5 hover:text-stone-200 aria-[current=page]:bg-amber-100/10 aria-[current=page]:text-amber-100"
          >
            {label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
