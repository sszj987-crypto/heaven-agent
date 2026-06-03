"""
灵魂档案蒸馏器：从聊天记录中一次性提取人格特征，智能合并到灵魂档案。

对大文件自动切分分段处理，支持断点续传：上传同一文件时从失败位置继续。

用法:
    distiller = SoulDistiller(llm_client, soul_loader, progress_dir=data_dir)
    result = await distiller.distill(chat_text)
    # result.changes → 有变化的维度名列表
    # result.profile → 更新后的全部维度内容
    # result.summary → LLM 分析摘要
"""

import hashlib
import json
import re
from pathlib import Path
from dataclasses import dataclass, field

from ..llm.client import LLMClient
from ..soul.loader import SoulLoader
from ..soul.profile import DIMENSION_NAMES
from ..config.logger import get_logger

log = get_logger("distiller")

# 单次 LLM 调用的文本上限（字节），超过则自动切分。
# 250KB UTF-8 中文 ≈ 85K 汉字 ≈ 110K tokens（实测 2.3 bytes/token）
# 加上 system prompt + 档案后总计约 115K tokens，128K 上下文窗口安全。
CHUNK_SIZE_BYTES = 250 * 1024  # 250KB

# 维度中文名
DIMENSION_LABELS: dict[str, str] = {
    "basic_info": "基本信息",
    "personality": "性格",
    "life_experiences": "人生经历",
    "relationships": "人际关系",
    "hobbies": "爱好",
    "special_habits": "特殊习惯",
    "values_beliefs": "价值观与信仰",
    "emotional_anchors": "情感锚点",
    "linguistic_fingerprint": "语言指纹",
    "knowledge_domain": "知识领域",
}


@dataclass
class DistillResult:
    """蒸馏结果"""
    changes: list[str] = field(default_factory=list)    # 有变化的维度名
    profile: dict[str, str] = field(default_factory=dict)  # 更新后的全维度
    summary: str = ""                                     # 分析摘要


class SoulDistiller:
    """从聊天记录批量提取人格特征，智能合并到灵魂档案。

    大文件自动切分为多段，每段独立分析后增量合并。
    支持断点续传：同一文件重复上传时从失败位置继续。
    """

    def __init__(self, llm_client: LLMClient, soul_loader: SoulLoader,
                 chunk_size_bytes: int = CHUNK_SIZE_BYTES,
                 progress_dir: Path | str | None = None):
        self._llm = llm_client
        self._loader = soul_loader
        self._chunk_size = chunk_size_bytes
        self._progress_dir = Path(progress_dir) if progress_dir else None
        log.info("SoulDistiller 初始化, chunk_size=%d bytes, progress_dir=%s",
                 self._chunk_size, self._progress_dir)

    # ── 公开接口 ──────────────────────────────────────────

    async def distill(self, chat_text: str) -> DistillResult:
        """
        分析聊天记录、更新灵魂档案。
        同一文件重复调用时自动从上次失败的 chunk 继续。

        Raises:
            ValueError: 聊天记录为空
            RuntimeError: 单段处理时 LLM 调用/解析失败
        """
        chat_text = chat_text.strip()
        if not chat_text:
            raise ValueError("聊天记录为空")

        profile = self._loader.load()
        text_bytes = len(chat_text.encode("utf-8"))
        file_hash = _hash_text(chat_text)
        log.info("蒸馏开始, chat_size=%d chars (%d bytes), soul=%s, hash=%s",
                 len(chat_text), text_bytes, profile.name, file_hash)

        chunks = self._split_chunks(chat_text) if text_bytes > self._chunk_size else None

        # 小文件：单次处理（不经过断点续传）
        if chunks is None:
            return await self._process_single(profile, chat_text)

        # 大文件：检查是否有断点可恢复
        progress = self._load_progress()
        if progress and progress.get("file_hash") == file_hash:
            resume_from = progress["resume_from"]
            if resume_from > 0:
                log.info("发现断点，从 chunk %d/%d 恢复（已跳过 %d 段）",
                         resume_from + 1, len(chunks), resume_from)
                # 恢复累积状态
                for dim, content in progress["accumulated_dims"].items():
                    profile.dimensions[dim] = content
                return await self._process_chunked(
                    profile, chunks,
                    resume_from=resume_from,
                    accumulated_dims=progress["accumulated_dims"],
                    all_changes=set(progress["all_changes"]),
                    summaries=progress["summaries"],
                    file_hash=file_hash,
                )
            else:
                log.info("上次的文件已全部完成，重新开始")

        # 全新开始
        return await self._process_chunked(
            profile, chunks,
            resume_from=0,
            accumulated_dims={},
            all_changes=set(),
            summaries=[],
            file_hash=file_hash,
        )

    # ── 单次处理 ──────────────────────────────────────────

    async def _process_single(self, profile, chat_text: str) -> DistillResult:
        """小文件直接一次 LLM 调用处理并保存。"""
        new_dimensions, summary = await self._call_llm(profile, chat_text)
        changes = self._save_changes(profile, new_dimensions)

        log.info("蒸馏完成 (single), changes=%s, summary=%s", changes, summary)
        return DistillResult(
            changes=changes,
            profile=self._merge_profile(profile, new_dimensions),
            summary=summary,
        )

    # ── 分段处理 ──────────────────────────────────────────

    async def _process_chunked(self, profile, chunks: list[str],
                               resume_from: int,
                               accumulated_dims: dict[str, str],
                               all_changes: set[str],
                               summaries: list[str],
                               file_hash: str) -> DistillResult:
        """逐段 LLM 调用，增量合并。支持断点续传。"""
        log.info("分段处理: %d chunks, 从第 %d 段开始", len(chunks), resume_from + 1)

        failed_chunks: list[int] = []

        for i in range(resume_from, len(chunks)):
            chunk = chunks[i]
            chunk_bytes = len(chunk.encode("utf-8"))
            log.info("处理 chunk %d/%d, size=%d chars (%d bytes)",
                     i + 1, len(chunks), len(chunk), chunk_bytes)

            try:
                new_dimensions, summary = await self._call_llm(profile, chunk)
            except Exception as e:
                log.warning("chunk %d/%d 处理失败（保存断点，跳过）: %s",
                           i + 1, len(chunks), e)
                failed_chunks.append(i + 1)
                # 保存断点：下次上传同一文件从这里继续
                self._save_progress(file_hash, i, accumulated_dims,
                                    sorted(all_changes), summaries)
                continue

            # 本段有变化的维度
            chunk_changes = []
            for dim in DIMENSION_NAMES:
                old_content = profile.dimensions.get(dim, "").strip()
                new_content = new_dimensions.get(dim, "").strip()
                if new_content and new_content != old_content:
                    chunk_changes.append(dim)
                    accumulated_dims[dim] = new_content
                    profile.dimensions[dim] = new_content

            all_changes.update(chunk_changes)

            if summary:
                summaries.append(f"[第{i+1}段] {summary}")

            if chunk_changes:
                log.info("chunk %d/%d 发现变化: %s", i + 1, len(chunks), chunk_changes)
            else:
                log.info("chunk %d/%d 无新发现", i + 1, len(chunks))

        # 全部处理完 → 保存落地 + 删除断点
        for dim in all_changes:
            try:
                self._loader.save_dimension(dim, accumulated_dims[dim])
            except Exception as e:
                log.error("保存维度 %s 失败: %s", dim, e)

        self._delete_progress()

        changes = sorted(all_changes)
        success_count = len(chunks) - len(failed_chunks)
        log.info("蒸馏完成 (chunked), %d/%d chunks 成功, changes=%s",
                 success_count, len(chunks), changes)

        if failed_chunks:
            summaries.append(
                f"[跳过: 第{','.join(map(str, failed_chunks))}段解析失败，"
                f"下次上传同一文件可续传]"
            )

        return DistillResult(
            changes=changes,
            profile=self._merge_profile(profile, accumulated_dims),
            summary=" | ".join(summaries) if summaries else "",
        )

    # ── 断点续传 ──────────────────────────────────────────

    def _progress_path(self) -> Path | None:
        """断点文件路径。"""
        if self._progress_dir is None:
            return None
        return self._progress_dir / ".distill_progress.json"

    def _load_progress(self) -> dict | None:
        """加载上次未完成的蒸馏进度。"""
        path = self._progress_path()
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception as e:
            log.warning("读取断点文件失败: %s", e)
            return None

    def _save_progress(self, file_hash: str, resume_from: int,
                       accumulated_dims: dict[str, str],
                       all_changes: list[str],
                       summaries: list[str]):
        """保存蒸馏进度到磁盘。"""
        path = self._progress_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "file_hash": file_hash,
                "resume_from": resume_from,
                "accumulated_dims": accumulated_dims,
                "all_changes": all_changes,
                "summaries": summaries,
            }, ensure_ascii=False, indent=2), "utf-8")
            log.info("断点已保存: resume_from=%d", resume_from)
        except Exception as e:
            log.error("保存断点失败: %s", e)

    def _delete_progress(self):
        """蒸馏全部完成后删除断点文件。"""
        path = self._progress_path()
        if path and path.exists():
            try:
                path.unlink()
                log.info("断点文件已删除（全部完成）")
            except Exception as e:
                log.warning("删除断点文件失败: %s", e)

    # ── LLM 调用 ──────────────────────────────────────────

    _DISTILL_TIMEOUT = 300
    _MAX_RETRIES = 2

    async def _call_llm(self, profile, chat_text: str) -> tuple[dict[str, str], str]:
        """调用 LLM 分析聊天记录，返回 (new_dimensions, summary)。含重试逻辑。"""
        messages = self._build_messages(profile, chat_text)

        last_error = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                if attempt > 0:
                    log.warning("蒸馏 LLM 重试 %d/%d", attempt, self._MAX_RETRIES)
                raw_response = await self._llm.chat(
                    messages, timeout=self._DISTILL_TIMEOUT, max_tokens=8192,
                    json_mode=True)
                break
            except Exception as e:
                last_error = e
                log.error("蒸馏 LLM 调用失败 (attempt %d/%d): %s",
                          attempt + 1, self._MAX_RETRIES + 1, e)
                if attempt < self._MAX_RETRIES:
                    import asyncio
                    await asyncio.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(
                f"LLM 调用失败（已重试 {self._MAX_RETRIES} 次）: {last_error}"
            ) from last_error

        log.debug("LLM 原始响应 (%d chars): %s",
                  len(raw_response), raw_response[:500])

        try:
            return self._parse_response(raw_response)
        except Exception as e:
            log.error("蒸馏响应解析失败: %s\nraw=%s", e, raw_response[:1000])
            raise RuntimeError(f"LLM 响应解析失败: {e}") from e

    # ── 保存变更 ──────────────────────────────────────────

    def _save_changes(self, profile, new_dimensions: dict[str, str]) -> list[str]:
        """对比新旧维度，保存有变化的维度。返回变化维度列表。"""
        changes = []
        for dim in DIMENSION_NAMES:
            old_content = profile.dimensions.get(dim, "").strip()
            new_content = new_dimensions.get(dim, "").strip()
            if new_content and new_content != old_content:
                try:
                    self._loader.save_dimension(dim, new_content)
                    changes.append(dim)
                    log.info("维度已更新: %s, old_len=%d, new_len=%d",
                             dim, len(old_content), len(new_content))
                except Exception as e:
                    log.error("保存维度 %s 失败: %s", dim, e)
        return changes

    @staticmethod
    def _merge_profile(profile, new_dimensions: dict[str, str]) -> dict[str, str]:
        """合并档案，新内容覆盖旧内容。"""
        return {
            dim: new_dimensions.get(dim, profile.dimensions.get(dim, ""))
            for dim in DIMENSION_NAMES
        }

    # ── 文本切分 ──────────────────────────────────────────

    def _split_chunks(self, text: str) -> list[str]:
        """
        在消息边界处切分文本，避免截断单条消息。
        优先在双换行处切分，其次单换行，最后硬切分。
        """
        chunks: list[str] = []
        remaining = text

        text_bytes = len(text.encode("utf-8"))
        avg_bytes_per_char = text_bytes / max(len(text), 1)
        target_chars = int(self._chunk_size / avg_bytes_per_char)
        min_split_chars = target_chars // 2

        while len(remaining.encode("utf-8")) > self._chunk_size * 1.2:
            probe = remaining[:target_chars]
            split_at = None

            # 策略 1: 双换行（消息边界）
            last_double_nl = probe.rfind("\n\n")
            if last_double_nl > min_split_chars:
                split_at = last_double_nl + 2
            else:
                # 策略 2: 单换行
                last_nl = probe.rfind("\n")
                if last_nl > min_split_chars:
                    split_at = last_nl + 1
                else:
                    # 策略 3: 扩展到 1.5x 范围找空格
                    extended = remaining[:int(target_chars * 1.5)]
                    last_space = extended.rfind(" ", min_split_chars)
                    if last_space > 0:
                        split_at = last_space + 1

            if split_at is None:
                split_at = target_chars

            chunk = remaining[:split_at].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[split_at:].strip()

        if remaining.strip():
            chunks.append(remaining.strip())

        return chunks

    # ── Prompt 构建 ───────────────────────────────────────

    def _build_messages(self, profile, chat_text: str) -> list[dict]:
        """构建 LLM 请求的 messages"""
        dimensions_md = self._format_current_profile(profile)

        return [
            {"role": "system", "content": _DISTILL_SYSTEM_PROMPT},
            {"role": "user", "content": _DISTILL_USER_TEMPLATE.format(
                dimensions_md=dimensions_md,
                chat_text=chat_text,
            )},
        ]

    def _format_current_profile(self, profile) -> str:
        """格式化当前档案为 prompt 文本"""
        parts = []
        for dim in DIMENSION_NAMES:
            content = profile.dimensions.get(dim, "").strip()
            label = DIMENSION_LABELS.get(dim, dim)
            if content:
                parts.append(f"### {label} ({dim})\n{content}")
            else:
                parts.append(f"### {label} ({dim})\n（暂无内容）")
        return "\n\n".join(parts)

    def _parse_response(self, raw: str) -> tuple[dict[str, str], str]:
        """解析 LLM 响应，提取维度内容和摘要。失败时尝试修复截断 JSON。"""
        text = raw.strip()
        text = _strip_markdown_fence(text)
        data = self._try_parse_json(text)

        dimensions = data.get("dimensions", {})
        summary = data.get("summary", "")

        filtered = {}
        for dim in DIMENSION_NAMES:
            val = dimensions.get(dim, "UNCHANGED")
            if val and val != "UNCHANGED":
                filtered[dim] = str(val)

        return filtered, str(summary)

    @staticmethod
    def _try_parse_json(text: str) -> dict:
        """尝试解析 JSON，截断时自动修复。"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fixes = [
            '"}',
            '"}}',
            '"\n}\n}',
            '"}]}',
            '",\n"summary": "分析完成"}}',
        ]
        for suffix in fixes:
            try:
                return json.loads(text + suffix)
            except json.JSONDecodeError:
                continue

        try:
            return SoulDistiller._recover_partial_json(text)
        except Exception:
            pass

        raise RuntimeError(
            f"JSON 解析失败且无法自动修复, text_len={len(text)}, "
            f"tail={repr(text[-100:])}"
        )

    @staticmethod
    def _recover_partial_json(text: str) -> dict:
        """从截断 JSON 中恢复已完成的维度内容。"""
        last_complete = 0
        for dim in DIMENSION_NAMES:
            pattern = f'"{dim}":'
            pos = text.rfind(pattern)
            if pos > last_complete:
                after = text[pos + len(pattern):].strip()
                if after.startswith('"') and _has_closing_quote(after):
                    last_complete = pos

        if last_complete == 0:
            raise RuntimeError("无法找到任何完整维度")

        recovered = text[:last_complete].rstrip().rstrip(",")
        recovered += '\n}\n}'
        return json.loads(recovered)


# ── helpers ────────────────────────────────────────────────

def _hash_text(text: str) -> str:
    """计算文本的短哈希，用于识别「同一文件」。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _has_closing_quote(text: str) -> bool:
    """检查字符串中是否有匹配的闭合引号。"""
    in_escape = False
    for char in text[1:]:
        if in_escape:
            in_escape = False
            continue
        if char == '\\':
            in_escape = True
            continue
        if char == '"':
            return True
    return False


def _strip_markdown_fence(text: str) -> str:
    """去除 ```json ... ``` 包裹"""
    if text.startswith("```"):
        lines = text.split("\n")
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip().startswith("```"):
                end_idx = i
                break
        if end_idx is not None:
            return "\n".join(lines[1:end_idx]).strip()
        elif len(lines) > 1:
            return "\n".join(lines[1:]).strip()
    return text


# ── Prompt 模板 ──────────────────────────────────────────────

_DISTILL_SYSTEM_PROMPT = """你是一个灵魂档案分析师。你的任务是从聊天记录中提取关于某个人的信息，更新其灵魂档案。

## 灵魂档案的 10 个维度

1. **basic_info** — 基本信息：姓名、性别、年龄、籍贯、职业、生卒年份等。格式：`字段: 值`
2. **personality** — 性格特征：性格标签（列表）、性格类型参考（如 MBTI）
3. **linguistic_fingerprint** — 语言指纹：口头禅、语气词（呀、呢、啦、嘛、吧、哦）、句式风格（短句/长句、爱用逗号/省略号）、幽默风格、敏感话题
4. **values_beliefs** — 价值观与信仰：人生哲学、金钱观、家庭观、教育观、事业观等
5. **knowledge_domain** — 知识领域：擅长的事和专业领域、不擅长的领域
6. **life_experiences** — 人生经历：按年份排列的重要事件（出生、求学、工作、婚姻、退休等）
7. **relationships** — 人际关系：重要的人，格式为 `- 姓名: 关系, 称呼, 备注`
8. **hobbies** — 爱好：爱好列表，格式为 `- 爱好名称: 备注说明`
9. **special_habits** — 特殊习惯：行为特点、饮食习惯、穿衣风格、作息习惯等
10. **emotional_anchors** — 情感锚点：重要的情感记忆，格式为 `- 事件简述: 情绪类型（如自豪/温暖/遗憾），描述`

## 合并规则（严格遵守）

1. **追加**：新信息与现有内容不矛盾时，追加到对应段落末尾
2. **保留**：新证据印证了已有内容时，保留原有内容不变
3. **替换**：新证据与现有内容明确矛盾时，用新内容替换旧条目
4. **创建**：发现了现有档案中完全没有的新信息，创建新的条目
5. **绝不删除**：除非存在明确矛盾，否则不删除任何已有描述
6. **证据优先**：只提取聊天记录中明确体现的信息，不要凭空推测

## 需要特别关注的信息

- 说话风格：口头禅、语气词使用频率、句子长短、标点符号习惯
- 情感表达：开心时怎么说、难过时怎么说、安慰人时怎么说
- 对人的称呼：怎么称呼配偶、孩子、朋友、同事
- 生活细节：吃什么、玩什么、日常习惯、特殊癖好
- 价值观线索：对金钱、家庭、工作、朋友的态度
"""

_DISTILL_USER_TEMPLATE = """## 当前灵魂档案

{dimensions_md}

## 聊天记录

{chat_text}

---

请分析以上聊天记录，对每个维度输出更新后的完整 markdown 内容。
如果某个维度根据聊天记录没有新发现、不需要更新，该维度的值设置为字符串 "UNCHANGED"。

输出格式为严格的 JSON 对象（不要用代码块包裹）：
{{
  "dimensions": {{
    "personality": "更新后的完整 markdown...",
    "linguistic_fingerprint": "更新后的完整 markdown...",
    "basic_info": "UNCHANGED"
  }},
  "summary": "用一句话总结从聊天记录中发现的关键人格线索"
}}"""
