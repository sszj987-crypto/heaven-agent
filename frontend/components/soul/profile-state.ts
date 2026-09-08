export function updateBasicInfoName(content: string, name: string): string {
  return /姓名[：:]\s*.+/.test(content)
    ? content.replace(/姓名[：:]\s*.+/, `姓名: ${name}`)
    : `姓名: ${name}\n${content}`;
}

export function shouldApplyDimensionResponse(requestId: number, latestId: number): boolean {
  return requestId === latestId;
}

export function canEditSoulName(activeTab: string): boolean {
  return activeTab === "basic_info";
}
