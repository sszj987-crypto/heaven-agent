import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "关于 Heaven Agent · 让思念有回响",
  description: "了解 Heaven Agent 的愿景、人物档案与纪念对话功能，以及本地和云端服务的数据使用边界。",
};

export default function AboutPage() {
  return (
    <article className="desktop-page space-y-10">
      <header className="border-b border-amber-100/10 pb-10">
        <p className="mb-4 text-sm text-stone-400">关于这个项目</p>
        <h1 className="text-4xl font-light tracking-wide text-stone-100">Heaven Agent</h1>
        <p className="mt-4 text-2xl font-light text-amber-100/80">让思念有回响</p>
        <p className="mt-5 max-w-3xl text-base leading-8 text-stone-400">
          一个本地优先的 AI 人物模拟与纪念对话应用。我们希望，以可整理的资料和对话承载记忆，
          让那些值得被记住的故事、习惯与表达，有一个可以慢慢整理、随时回看的地方。
        </p>
      </header>

      <section aria-labelledby="features-title" className="space-y-6">
        <h2 id="features-title" className="text-lg font-medium text-stone-200">现在可以做什么</h2>
        <dl className="grid grid-cols-3 gap-8">
          <div>
            <dt className="mb-3 text-base text-stone-200">整理人物档案</dt>
            <dd className="text-sm leading-7 text-stone-400">用六维档案记录人物信息，导入资料并审阅候选事实；确认后再写入，始终保留你的判断。</dd>
          </div>
          <div>
            <dt className="mb-3 text-base text-stone-200">带着记忆对话</dt>
            <dd className="text-sm leading-7 text-stone-400">结合档案与检索到的记忆进行文字对话，查看回复参考的记忆。AI 自己的回复不会自动成为人物事实。</dd>
          </div>
          <div>
            <dt className="mb-3 text-base text-stone-200">让文字有声音</dt>
            <dd className="text-sm leading-7 text-stone-400">支持语音输入，以及本地或 MiniMax 云端语音合成。在档案中管理参考声音和音色，文字先显示，点击后生成并播放语音。</dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="boundaries-title" className="space-y-5 border-t border-amber-100/10 pt-8">
        <h2 id="boundaries-title" className="text-lg font-medium text-stone-200">关于模拟与数据</h2>
        <div className="settings-grid text-sm leading-7 text-stone-400">
          <div className="space-y-3">
            <h3 className="font-medium text-stone-300">承载记忆，不代表真实人物</h3>
            <p>对话是基于资料生成的 AI 人物模拟，并非人物本人，回复可能不准确，也不能代替真实关系或专业支持。你可以查看、修正资料，并决定哪些候选内容成为档案的一部分。</p>
          </div>
          <div className="space-y-3">
            <h3 className="font-medium text-stone-300">本地优先，不等于完全离线</h3>
            <p>档案、对话和声音资料保存在本机。使用云端对话服务时，生成回复所需的档案、记忆及对话内容会发送给你配置的服务商。</p>
            <p>本地语音由本机处理；使用 MiniMax 时，音色复刻会发送参考录音，语音合成会发送待朗读文字。云端服务可能产生费用，请仅使用已获授权的资料与声音。</p>
          </div>
        </div>
      </section>

      <footer className="flex items-center justify-between gap-8 border-t border-amber-100/10 pt-8">
        <div>
          <h2 className="text-base font-medium text-stone-200">一起让它更好</h2>
          <p className="mt-2 text-sm text-stone-400">查看项目源码、使用说明，或反馈你遇到的问题。</p>
        </div>
        <a href="https://github.com/sszj987-crypto/heaven-agent" target="_blank" rel="noopener noreferrer" className="shrink-0 rounded-lg border border-amber-100/20 px-5 py-3 text-sm text-amber-100/80 transition-colors hover:bg-amber-100/5">
          GitHub 仓库<span className="sr-only">（在新标签页打开）</span>
        </a>
      </footer>
    </article>
  );
}
