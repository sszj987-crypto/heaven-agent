export const DIMENSION_LABELS: Record<string, string> = {
  basic_info: "基本信息",
  personality: "性格",
  life_experiences: "人生经历",
  relationships: "人际关系",
  personal_traits: "个人特质",
  emotional_anchors: "情感锚点",
};

export const DIMENSIONS = Object.keys(DIMENSION_LABELS);

export const SPECIAL_TABS = [
  { key: "candidates", label: "待确认事实", accent: true },
  { key: "scene", label: "所在场景" },
  { key: "voice", label: "语音音色" },
  { key: "distill", label: "聊天记录蒸馏" },
  { key: "skill", label: "行为规则" },
  { key: "memory", label: "记忆可视化", divider: true },
] as const;
