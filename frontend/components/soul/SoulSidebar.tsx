import { DIMENSIONS, DIMENSION_LABELS, SPECIAL_TABS } from "./constants";


export default function SoulSidebar({
  activeTab,
  soulName,
  nameEditable,
  onNameChange,
  onSelect,
}: {
  activeTab: string;
  soulName: string;
  nameEditable: boolean;
  onNameChange: (name: string) => void;
  onSelect: (tab: string) => void;
}) {
  const buttonClass = (key: string, accent = false) =>
    `w-full text-left px-4 py-2.5 text-sm transition-colors ${
      activeTab === key
        ? accent
          ? "bg-amber-100/10 text-amber-100/80"
          : "bg-white/10 text-white/80"
        : "text-white/40 hover:text-white/60 hover:bg-white/5"
    }`;

  return (
    <aside className="w-48 border-r border-white/10 overflow-y-auto shrink-0 flex flex-col">
      <div className="px-3 py-2 border-b border-white/5">
        <input
          value={soulName}
          disabled={!nameEditable}
          onChange={(event) => onNameChange(event.target.value)}
          className="w-full bg-transparent text-sm font-medium text-white/70 outline-none border border-transparent focus:border-white/20 rounded px-1.5 py-0.5 transition-colors disabled:cursor-not-allowed disabled:text-white/35"
          placeholder="输入姓名"
        />
      </div>
      {DIMENSIONS.map((dimension) => (
        <button
          key={dimension}
          onClick={() => onSelect(dimension)}
          className={buttonClass(dimension)}
        >
          {DIMENSION_LABELS[dimension]}
        </button>
      ))}
      <div className="border-t border-white/5 my-1" />
      {SPECIAL_TABS.map((tab) => (
        <div key={tab.key}>
          {"divider" in tab && tab.divider && <div className="border-t border-white/5 my-1" />}
          <button
            onClick={() => onSelect(tab.key)}
            className={buttonClass(tab.key, "accent" in tab && Boolean(tab.accent))}
          >
            {tab.label}
          </button>
        </div>
      ))}
    </aside>
  );
}
