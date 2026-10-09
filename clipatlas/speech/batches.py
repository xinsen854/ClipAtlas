"""Deterministic Markdown splitting and filename matching; no AI calls."""

import re
import unicodedata
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from clipatlas.speech.models import utc_now

MAX_BATCH_ENTRIES = 100


class ExportRatio(StrEnum):
    LANDSCAPE_16_9 = "16:9"
    PORTRAIT_9_16 = "9:16"
    SQUARE_1_1 = "1:1"


def export_ratio_resolution(ratio: str) -> tuple[int, int]:
    """Map a batch export ratio to a canvas resolution (width, height)."""
    return {
        ExportRatio.LANDSCAPE_16_9: (1920, 1080),
        ExportRatio.PORTRAIT_9_16: (1080, 1920),
        ExportRatio.SQUARE_1_1: (1080, 1080),
    }[ExportRatio(ratio)]
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_CODE = re.compile(r"^(?:文案\s*)?[\[【(（]?([0-9]{1,4})(?:[\]】)）]|[\s_.、:：\-｜|]|[条篇])")
# 批量规则：元数据行（封面标题/标题/片名/文件名等）不朗读，不参与旁白对齐；
# “口播内容：”只是正文前缀，也不进入对齐文本。
# 元数据行允许带编号前缀（如“46.封面标题：长假跑长途”）。
# 标签词写宽，覆盖常见写法：封面标题/标题/片名/文件名/文案标题/标题文案/作品标题等。
_COVER_LABELS = (
    r"封面\s*标题|文案\s*标题|标题\s*文案|作品\s*标题|片头\s*标题|视频\s*标题|"
    r"标题|片名|文件名"
)
_SCRIPT_META = re.compile(
    rf"^\s*(?:[0-9０-９]{{1,4}}\s*[.．、\-]\s*)?(?:{_COVER_LABELS})\s*[：:]"
)
_SCRIPT_BODY = re.compile(
    r"^\s*(?:口播内容|口播文案|口播|正文内容|旁白内容|旁白|正文|文案内容|朗读内容|内容)\s*[：:]\s*"
)
# 书名号标题行：《xxx》整行作为封面标题（不朗读），如 t5 素材格式。
_BRACKET_TITLE = re.compile(r"^\s*《(.+?)》\s*$")
# 话题标签：#xxx# 不朗读。整行都是标签时删行，行内标签也删除。
_HASHTAG = re.compile(r"#([^#\n]+)#")
# 方向标注元数据行，如 “（方向1 · 悦野五+用户生态）”：整行剥离，不朗读、不参与对齐。
_DIRECTION_META = re.compile(
    r"^\s*[（(]\s*方向\s*[0-9０-９一二三四五六七八九十]{1,3}\s*[·.．、,，]\s*.+?[）)]\s*$"
)
_COVER_TITLE = re.compile(
    rf"^\s*(?:[0-9０-９]{{1,4}}\s*[.．、\-]\s*)?(?:{_COVER_LABELS})\s*[：:]\s*(.+?)\s*$"
)
_MAX_COVER_TITLE_LEN = 40


def extract_cover_title(title: str) -> str | None:
    """从批量文案首行提取封面标题（草稿命名用）。

    支持三类写法：
    1. 显式标签：“封面标题：XXX”、“46.标题：XXX”、“文案标题：XXX”；
    2. 无标签的编号标题行：“1. 长假跑长途”、“文案1：标题”、“第1条：标题”；
    3. 没有可识别标题时返回 None，由调用方回退到口播第一句。

    编号行只有在文本是“标题样”（短、无句末标点）时才当作标题，
    避免把整段正文误当封面标题。
    """
    if not title:
        return None
    stripped = title.strip()
    match = _COVER_TITLE.match(stripped)
    if match:
        return match.group(1)
    bracket = _BRACKET_TITLE.match(stripped)
    if bracket:
        return bracket.group(1).strip()
    numbered = _NUMBERED_COVER.match(stripped)
    if numbered:
        text = numbered.group("text").strip()
        if (
            len(text) <= _MAX_COVER_TITLE_LEN
            and not re.search(r"[。！!；;]", text)
        ):
            return text
    return None
_NUMBER_TOKEN = r"(?:[0-9０-９]{1,4}|[零〇一二两三四五六七八九十百]{1,6})"
# 无显式标签的编号标题行，如 “1. 长假跑长途”、“文案1：标题”、“第1条：标题”。
_NUMBERED_COVER = re.compile(
    rf"^\s*(?:文案\s*)?(?:第\s*)?(?P<num>{_NUMBER_TOKEN})\s*(?:[条篇])?\s*(?:[：:、.．\-｜|]|\s+)(?P<text>.+?)\s*$"
)
_LABEL_END = r"(?:\s*[：:、.．_\-｜|]|\s+|$)"
_NUMBERED = re.compile(
    rf"^(?:"
    rf"文案\s*(?P<label>{_NUMBER_TOKEN})(?:[条篇])?{_LABEL_END}"
    rf"|第\s*(?P<ordinal>{_NUMBER_TOKEN})\s*[条篇]{_LABEL_END}"
    rf"|[（(【\[](?P<bracket>{_NUMBER_TOKEN})[）)】\]]\s*[：:、.．_\-｜|]?"
    rf"|(?P<plain>{_NUMBER_TOKEN})\s*(?:\\?[.．](?![0-9０-９])|[、)）｜|])"
    rf")\s*(?P<text>.*)$"
)


def clean_script_text(text: str) -> str:
    """批量规则：只保留实际朗读文本，供解析与旁白对齐使用。

    - 行首为“封面标题：/标题：/片名：/文件名：”的整行（元数据）剥离；
    - 《书名号标题》整行剥离（作为封面标题，不朗读）；
    - 行首为“口播内容：/正文：/旁白：”的只去掉前缀；
    - #话题标签# 不朗读：整行标签删行，行内标签删除；
    - 其余行原样保留，顺序不变。
    """
    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if (
            _SCRIPT_META.match(stripped)
            or _BRACKET_TITLE.match(stripped)
            or _DIRECTION_META.match(stripped)
        ):
            continue
        if stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            continue
        if _SCRIPT_BODY.match(stripped):
            without = _HASHTAG.sub("", _SCRIPT_BODY.sub("", stripped)).replace("**", "")
            if without.strip():
                cleaned.append(without)
        else:
            without = _HASHTAG.sub("", line).replace("**", "")
            if without.strip():
                cleaned.append(without)
    return "\n".join(cleaned).strip()


def _number(value: str) -> int:
    normalized = unicodedata.normalize("NFKC", value)
    if normalized.isdecimal():
        return int(normalized)
    digits = {c: i for i, c in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    if all(c in digits for c in normalized):
        return int("".join(str(digits[c]) for c in normalized))
    total = current = 0
    for char in normalized:
        if char in digits:
            current = digits[char]
        else:
            total += (current or 1) * {"十": 10, "百": 100}[char]
            current = 0
    return total + current


def _numbered_line(line: str) -> tuple[int, str, str, str] | None:
    indent = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())
    title = line.strip()
    if title.startswith("**") and title.endswith("**"):
        title = title[2:-2].strip()
    match = _NUMBERED.match(title)
    if match is None:
        return None
    token = next(match[name] for name in ("label", "ordinal", "bracket", "plain") if match[name])
    return indent, str(_number(token)).zfill(3), title, match['text'].strip()


class BatchScript(BaseModel):
    id: str
    code: str | None = None
    title: str
    text: str


class BatchAudioFile(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    size: int = Field(gt=0, le=100 * 1024 * 1024)


class BatchMatch(BaseModel):
    script: BatchScript
    audio_index: int | None = None
    reason: str
    candidates: list[int] = Field(default_factory=list)


class BatchEntry(BatchScript):
    audio_name: str
    audio_size: int
    audio_sha256: str | None = None
    narration_track_id: UUID | None = None
    duration_ms: int | None = None
    plan_id: UUID | None = None
    last_error: str | None = None


class NarrationBatch(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    name: str
    top_k: int = Field(default=12, ge=1, le=100)
    export_ratio: str = "16:9"
    entries: list[BatchEntry]
    assignment_revision: int = Field(default=0, ge=0)
    assignment_order: list[str] = Field(default_factory=list)
    candidate_snapshot: dict[str, list[dict[str, object]]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BatchSummary(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    entry_count: int
    created_at: datetime


def entry_code(value: str) -> str | None:
    value = unicodedata.normalize("NFKC", value).strip()
    if re.fullmatch(r"[0-9]{1,4}", value):
        return str(int(value)).zfill(3)
    match = _CODE.match(value)
    if match:
        return str(int(match.group(1))).zfill(3)
    numbered = _numbered_line(value)
    return numbered[1] if numbered else None


def _key(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def parse_batch_markdown(markdown: str) -> list[BatchScript]:
    lines = markdown.lstrip("\ufeff").replace("\r\n", "\n").splitlines()
    headings: list[tuple[int, int, str]] = []
    separators: list[int] = []
    numbered: list[tuple[int, int, str, str]] = []
    meta_bounds: list[tuple[int, str]] = []
    fence: str | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is not None:
            continue
        boundary = _numbered_line(line)
        if boundary is not None:
            indent, _, title, content = boundary
            numbered.append((index, indent, title, content))
        # 无编号的元数据标题行（封面标题：/《》标题）也作为分段边界，
        # 支持“封面标题：X 口播内容：Y 封面标题：Z 口播内容：W”连续排列的文案稿。
        elif (
            _SCRIPT_META.match(stripped)
            or _BRACKET_TITLE.match(stripped)
        ) and not _DIRECTION_META.match(stripped):
            meta_bounds.append((index, stripped))
        match = _HEADING.match(line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2)))
        elif re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            separators.append(index)

    pieces: list[tuple[str, str]] = []
    chosen: list[tuple[int, int, str]] = []
    if headings:
        h1 = [h for h in headings if h[1] == 1]
        h2 = [h for h in headings if h[1] == 2]
        chosen = h1 if len(h1) > 1 else h2 or h1 or [
            h for h in headings if h[1] == min(x[1] for x in headings)
        ]
    # Only outermost list items can be batch boundaries. Keep ordinary preambles
    # and nested numbered lists inside a single script instead of discarding them.
    if numbered:
        outer_indent = min(item[1] for item in numbered)
        numbered = [item for item in numbered if item[1] == outer_indent]
        first = numbered[0][0]
        preamble = [i for i in range(first) if lines[i].strip()]
        wrapper_only = len(chosen) == 1 and preamble == [chosen[0][0]]
        if len(numbered) < 2 or (preamble and not wrapper_only):
            numbered = []
    if chosen and not (len(chosen) == 1 and numbered and not separators):
        for offset, (index, _, title) in enumerate(chosen):
            end = chosen[offset + 1][0] if offset + 1 < len(chosen) else len(lines)
            pieces.append((title, "\n".join(lines[index + 1:end]).strip()))
    elif numbered and not separators:
        for offset, (index, _, title, content) in enumerate(numbered):
            end = numbered[offset + 1][0] if offset + 1 < len(numbered) else len(lines)
            following = "\n".join(lines[index + 1:end]).strip()
            # A long first line may contain both title and body. Never discard it.
            bold_title = content.startswith("**") and content.endswith("**") and len(content) > 4
            # 竖线分隔的编号标题行（如 “01｜标题”）是纯标题，不并入正文；
            # 只有点号/顿号等旧式分隔才按“编号+正文同行”判断。
            pipe_title = bool(re.match(rf"^\s*{_NUMBER_TOKEN}\s*[｜|]", title))
            inline_body = (not bold_title) and not pipe_title and (
                not following or len(content) > 120 or bool(
                    re.search(r"[。！？!?]|(?<!\d)\.(?:\s|$)", content)
                )
            )
            text = "\n".join(part for part in ([content, following] if inline_body else [following]) if part)
            pieces.append((title[:120], text))
    elif meta_bounds and not separators:
        # “封面标题：X 口播内容：Y …”连续排列：每个标题行开一条新文案。
        for offset, (index, title) in enumerate(meta_bounds):
            end = meta_bounds[offset + 1][0] if offset + 1 < len(meta_bounds) else len(lines)
            text = "\n".join(lines[index + 1:end]).strip()
            if text:
                pieces.append((title[:120], text))
    else:
        boundaries = [-1, *separators, len(lines)]
        for start, end in pairwise(boundaries):
            text = "\n".join(lines[start + 1:end]).strip()
            if text:
                pieces.append((text.splitlines()[0][:120], text))
    if not pieces:
        raise ValueError("MD 中没有可导入的文案")
    if len(pieces) > MAX_BATCH_ENTRIES:
        raise ValueError("每批最多100条文案，请拆分为多个MD文件")
    codes: set[str] = set()
    result = []
    for number, (title, text) in enumerate(pieces, 1):
        text = clean_script_text(text)
        if not text:
            raise ValueError(f"第{number}条“{title}”没有正文")
        code = entry_code(title)
        if code and code in codes:
            raise ValueError(f"文案编号{code}重复，请修改MD后重新预览")
        if code:
            codes.add(code)
        result.append(BatchScript(id=f"entry-{number:03d}", code=code, title=title, text=text))
    return result


def match_batch_audio(scripts: list[BatchScript], files: list[BatchAudioFile]) -> list[BatchMatch]:
    stems = [PurePosixPath(f.name.replace("\\", "/")).stem for f in files]
    codes = [entry_code(stem) for stem in stems]
    keys = [_key(stem) for stem in stems]
    matches = []
    for script in scripts:
        candidates = [i for i, code in enumerate(codes) if script.code and code == script.code]
        reason = "编号匹配"
        allowed = [i for i, code in enumerate(codes) if not script.code or not code or code == script.code]
        if not candidates:
            title = unicodedata.normalize("NFKC", script.title)
            prefix = _CODE.match(title)
            titles = {_key(title)}
            if prefix:
                titles.add(_key(title[prefix.end():]))
            marker = _numbered_line(title)
            if marker:
                titles.add(_key(marker[3]))
            candidates = [i for i in allowed if keys[i] and keys[i] in titles]
            reason = "标题匹配"
        if not candidates:
            paragraph = _key(re.split(r"\n\s*\n", script.text, maxsplit=1)[0])
            candidates = [i for i in allowed if keys[i] and keys[i] == paragraph]
            reason = "首段匹配"
            if not candidates:
                candidates = [i for i in allowed if len(keys[i]) >= 12 and paragraph.startswith(keys[i])]
                reason = "首段开头匹配，请核对"
        matches.append(BatchMatch(
            script=script, candidates=candidates,
            audio_index=candidates[0] if len(candidates) == 1 else None,
            reason=reason if len(candidates) == 1 else "多个候选，需手选" if candidates else "未匹配，需手选",
        ))
    used = [m.audio_index for m in matches if m.audio_index is not None]
    for match in matches:
        if match.audio_index is not None and used.count(match.audio_index) > 1:
            match.audio_index = None
            match.reason = "同一旁白匹配多条文案，需手选"
    return matches
