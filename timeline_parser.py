from __future__ import annotations

import re
from dataclasses import dataclass


TIMESTAMP_RE = re.compile(r"(?<!\d)(?P<timestamp>(?:\d{1,2}:)?\d{1,2}:\d{2})(?!\d)")
TIMELINE_MARKER_RE = re.compile(
    r"("
    r"\u30bf\u30a4\u30e0\s*\u30b9\u30bf\u30f3\u30d7|"
    r"time\s*stamps?|"
    r"timestamps?|"
    r"\u30bb\u30c3\u30c8\s*\u30ea\u30b9\u30c8|"
    r"set\s*lists?|"
    r"setlists?|"
    r"\u30bb\u30c8\u30ea|"
    r"\u66f2\s*\u30ea\u30b9\u30c8|"
    r"songs?\s*lists?"
    r")",
    re.IGNORECASE,
)
LINE_RE = re.compile(
    r"^\s*(?P<prefix>(?:[-*+>~#]|\d+[\.)\]]|\[\s*\d+\s*\])?)\s*"
    r"(?P<timestamp>(?:\d{1,2}:)?\d{1,2}:\d{2})"
    r"\s*(?P<title>.+?)\s*$"
)
BRACKETED_NOTE_RE = re.compile(r"[\(\[\{<].*?[\)\]\}>]")
FULLWIDTH_BRACKETED_NOTE_RE = re.compile(
    r"[\u3010\uff08\u300c\u300e\u3008\u300a].*?[\u3011\uff09\u300d\u300f\u3009\u300b]"
)
WHITESPACE_RE = re.compile(r"\s+")
BRACKET_TITLE_RE = re.compile(r"^\s*(?:\d+\u756a\u306e\u307f\s*)?[\[\uff3b](?P<title>.+?)[\]\uff3d].*$")
SETLIST_NUMBER_RE = re.compile(
    r"^\s*(?:\[\s*\d+\s*\]|\(\s*\d+\s*\)|\uff08\s*\d+\s*\uff09|\d+[\.)\u3001]|\d{1,3}\s+|\d{1,3}(?=[\[\u3010\uff3b])|\d{1,3}\u66f2\u76ee\s*)\s*"
)
DATE_MARKER_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}\s*\u65e5?")
COUNT_PERSON_RE = re.compile(r"\d[\d,]*\s*\u4eba")
LEADING_DECORATION_RE = re.compile(r"^[\s\-*:|/\\~>#\u2010-\u2015\uff1a\uff5c\uff0f]+")
TRAILING_DECORATION_RE = re.compile(r"[\s\-*:|/\\~>#\u2010-\u2015\uff1a\uff5c\uff0f]+$")
ARTIST_SEPARATOR_RE = re.compile(r"\s(?:-|/|\||\u2013|\u2014|\uff0f|\uff5c)\s|[/\uff0f]")

NON_SONG_KEYWORDS = (
    "mc",
    "talk",
    "chat",
    "free talk",
    "zatsu",
    "opening",
    "ending",
    "start",
    "end",
    "break",
    "superchat",
    "reading",
    "comment",
    "encore",
    "announcement",
    "notice",
    "\u96d1\u8ac7",  # zatsudan/chat
    "\u6328\u62f6",  # greeting
    "\u958b\u59cb",
    "\u914d\u4fe1\u958b\u59cb",
    "\u914d\u4fe1",
    "\u914d\u4fe1\u4e88\u5b9a",
    "\u30b2\u30fc\u30e0\u914d\u4fe1",
    "\u4e88\u5b9a",
    "\u5831\u544a",
    "\u7a81\u7834",
    "\u9054\u6210",
    "\u7761\u7720",
    "\u5468\u5e74",
    "\u30b9\u30b1\u30b8\u30e5\u30fc\u30eb",
    "\u904b\u8ee2",
    "\u30b0\u30c3\u30ba",
    "\u767a\u9001",
    "\u7279\u5178",
    "\u30dc\u30a4\u30b9",
    "\u30e1\u30f3\u9650",
    "asmr",
    "fanbox",
    "\u30d7\u30e9\u30f3",
    "\u5909\u66f4",
    "\u65c5\u884c",
    "\u7d42\u4e86",
    "\u7d42\u308f\u308a",
    "\u304a\u3064",
    "\u544a\u77e5",
    "\u5ba3\u4f1d",
    "\u304a\u77e5\u3089\u305b",
    "\u4f11\u61a9",
    "\u30b9\u30d1\u30c1\u30e3",
    "\u30b9\u30fc\u30d1\u30fc\u30c1\u30e3\u30c3\u30c8",
    "\u6717\u8aad",
    "\u8aad\u307f",
    "\u611f\u60f3",
    "\u632f\u308a\u8fd4\u308a",
    "\u304a\u540d\u524d\u547c\u3073",
    "\u540d\u524d\u547c\u3073",
    "\u5f85\u6a5f",
    "\u6e96\u5099",
    "\u97f3\u91cf",
    "\u30de\u30a4\u30af",
    "\u30b3\u30e1\u30f3\u30c8",
    "\u9045\u523b",
    "\u30a8\u30f3\u30c7\u30a3\u30f3\u30b0",
    "\u767b\u5834",
    "\u8a95\u751f\u65e5",
    "\u304a\u3081\u3067\u3068\u3046",
    "\u30d7\u30ec\u30bc\u30f3\u30c8",
    "\u8a95\u751f\u79d8\u8a71",
    "\u79d8\u8a71",
    "\u8a71\u984c",
    "\u3053\u3093\u3057\u3083\u3044\u308b",
    "\u3057\u3083\u308b\u304a",
    "\u3057\u3083\u308b\u3081\u3044\u3068",
    "\u5727\u3057\u3083\u3044\u308b",
    "\u5e72\u3057\u828b",
    "\u6821\u820e\u88cf",
    "\u5915\u98ef",
    "\u30dd\u30e0\u306e\u6a39",
    "\u30d5\u30eb\u30dc\u30c3\u30b3\u30bf\u30a4\u30e0",
)
NON_SONG_EXACT = {
    "op",
    "ed",
    "start",
    "end",
    "mc",
    "talk",
    "a\u30d1\u30fc\u30c8",
    "b\u30d1\u30fc\u30c8",
    "c\u30d1\u30fc\u30c8",
}
SONG_HINT_KEYWORDS = (
    "cover",
    "original",
    "song",
    "sing",
    "karaoke",
    "feat",
    "ft.",
    "\u6b4c",
    "\u66f2",
)


@dataclass(frozen=True)
class TimelineEntry:
    timestamp_text: str
    seconds: int
    raw_song_title: str
    normalized_song_title: str


@dataclass(frozen=True)
class TimelineCandidate:
    comment_text: str
    entries: list[TimelineEntry]
    score: int
    has_marker: bool


def timestamp_to_seconds(timestamp_text: str) -> int:
    parts = [int(part) for part in timestamp_text.strip().split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError(f"Unsupported timestamp format: {timestamp_text}")


def clean_song_title(title: str) -> str:
    cleaned = title.strip()
    bracket_match = BRACKET_TITLE_RE.match(cleaned)
    if bracket_match:
        cleaned = bracket_match.group("title")
    else:
        for marker in ("[", "\uff3b"):
            if marker in cleaned:
                candidate = cleaned.split(marker, 1)[1].strip("[]\uff3b\uff3d ")
                if "/" in candidate or "\uff0f" in candidate:
                    cleaned = candidate
                break
    cleaned = SETLIST_NUMBER_RE.sub("", cleaned)
    cleaned = LEADING_DECORATION_RE.sub("", cleaned)
    cleaned = TRAILING_DECORATION_RE.sub("", cleaned)
    cleaned = cleaned.strip("[]\uff3b\uff3d")
    if "/" in cleaned or "\uff0f" in cleaned:
        cleaned = re.sub(r"^\d{1,3}(?=[A-Za-z\u3040-\u30ff\u3400-\u9fff])", "", cleaned)
    cleaned = WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def normalize_song_title(title: str) -> str:
    normalized = title.replace("\u3000", " ")
    normalized = SETLIST_NUMBER_RE.sub("", normalized)
    normalized = BRACKETED_NOTE_RE.sub(" ", normalized)
    normalized = FULLWIDTH_BRACKETED_NOTE_RE.sub(" ", normalized)
    normalized = LEADING_DECORATION_RE.sub("", normalized)
    normalized = TRAILING_DECORATION_RE.sub("", normalized)
    normalized = WHITESPACE_RE.sub(" ", normalized)
    normalized = normalized.casefold()
    return normalized.strip()


def is_probable_song_title(
    raw_title: str,
    normalized_title: str,
    has_setlist_number: bool = False,
) -> bool:
    if not normalized_title:
        return False

    compact = normalized_title.replace(" ", "")
    if len(compact) < 2:
        return False

    if TIMESTAMP_RE.search(raw_title):
        return False

    if DATE_MARKER_RE.search(raw_title) and not ARTIST_SEPARATOR_RE.search(raw_title):
        return False

    if COUNT_PERSON_RE.search(raw_title):
        return False

    if ARTIST_SEPARATOR_RE.search(raw_title):
        return True

    if looks_like_non_song(raw_title, normalized_title):
        return False

    if any(keyword in normalized_title for keyword in SONG_HINT_KEYWORDS):
        return True

    # Numbered setlists often contain bare song titles without artist names.
    # Keep them, but only after the non-song checks above.
    if has_setlist_number and (has_letter(normalized_title) or has_cjk(normalized_title)):
        return True

    # Many fan timelines use bare song titles, e.g. "KING" or Japanese titles
    # without artist names. Accept them only after rejecting obvious chat markers.
    if has_letter(normalized_title) or has_cjk(normalized_title):
        return True

    return False


def looks_like_non_song(raw_title: str, normalized_title: str) -> bool:
    compact = normalized_title.replace(" ", "")
    raw_folded = raw_title.casefold()
    if compact in NON_SONG_EXACT:
        return True

    if any(keyword in normalized_title or keyword in raw_folded for keyword in NON_SONG_KEYWORDS):
        return True

    if contains_explanatory_marker(raw_title):
        return True

    if contains_question_marker(normalized_title):
        return True

    if compact.startswith(("op:", "ed:", "mc:")):
        return True

    if is_quoted_phrase(raw_title) and not ARTIST_SEPARATOR_RE.search(raw_title):
        return True

    return False


def contains_question_marker(value: str) -> bool:
    return "?" in value or "\uff1f" in value


def contains_explanatory_marker(value: str) -> bool:
    return "=" in value or "\uff1d" in value


def is_quoted_phrase(value: str) -> bool:
    stripped = value.strip()
    quote_pairs = (
        ('"', '"'),
        ("'", "'"),
        ("\u300c", "\u300d"),
        ("\u300e", "\u300f"),
        ("\u201c", "\u201d"),
    )
    return any(stripped.startswith(left) and stripped.endswith(right) for left, right in quote_pairs)


def has_letter(value: str) -> bool:
    return any(char.isalpha() for char in value)


def has_cjk(value: str) -> bool:
    return any(is_cjk(char) for char in value)


def is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3040 <= codepoint <= 0x30FF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xAC00 <= codepoint <= 0xD7AF
    )


def line_has_setlist_number(line: str, title: str) -> bool:
    before_title = line[: line.rfind(title)] if title in line else line
    return bool(re.search(r"(?:^|\s)(?:\[\s*\d+\s*\]|\d+[\.)\u3001])", before_title))


def parse_timeline_entries(comment_text: str) -> list[TimelineEntry]:
    """Parse likely song timeline entries from one YouTube comment."""
    candidate = build_timeline_candidate(comment_text)
    return candidate.entries if candidate else []

def select_best_timeline_comment(comment_texts: list[str]) -> TimelineCandidate | None:
    candidates = [
        candidate
        for comment_text in comment_texts
        if (candidate := build_timeline_candidate(comment_text)) is not None
    ]
    if not candidates:
        return None

    marker_candidates = [candidate for candidate in candidates if candidate.has_marker]
    if marker_candidates:
        return max(marker_candidates, key=lambda candidate: (candidate.score, len(candidate.entries)))

    return max(candidates, key=lambda candidate: (candidate.score, len(candidate.entries)))


def build_timeline_candidate(comment_text: str) -> TimelineCandidate | None:
    if len(TIMESTAMP_RE.findall(comment_text)) < 2:
        return None

    lines = comment_text.splitlines()
    marker_indexes = [
        index
        for index, line in enumerate(lines)
        if TIMELINE_MARKER_RE.search(line)
    ]
    has_marker = bool(marker_indexes)

    blocks: list[list[TimelineEntry]] = []
    if has_marker:
        for marker_index in marker_indexes:
            blocks.extend(
                parse_timeline_blocks(
                    lines=lines,
                    start_index=marker_index,
                    stop_after_first=True,
                )
            )
    else:
        blocks = parse_timeline_blocks(
            lines=lines,
            start_index=0,
            stop_after_first=False,
        )

    blocks = [block for block in blocks if len(block) >= 2]
    if not blocks:
        return None

    entries = max(blocks, key=lambda block: (len(block), timeline_span(block)))
    return TimelineCandidate(
        comment_text=comment_text,
        entries=entries,
        score=score_timeline_candidate(entries, has_marker),
        has_marker=has_marker,
    )


def parse_timeline_blocks(
    lines: list[str],
    start_index: int,
    stop_after_first: bool,
) -> list[list[TimelineEntry]]:
    blocks: list[list[TimelineEntry]] = []
    current: list[TimelineEntry] = []
    skipped_before_first = 0

    for line in lines[start_index:]:
        entry = parse_timeline_line(line)
        if entry is not None:
            current.append(entry)
            skipped_before_first = 0
            continue

        if not current:
            if is_blank_or_decoration(line) or TIMELINE_MARKER_RE.search(line):
                continue
            skipped_before_first += 1
            if stop_after_first and skipped_before_first > 5:
                break
            continue

        blocks.append(current)
        if stop_after_first:
            return blocks
        current = []

    if current:
        blocks.append(current)
    return blocks


def parse_timeline_line(line: str) -> TimelineEntry | None:
    match = LINE_RE.match(line)
    if not match:
        return None

    timestamp_text = match.group("timestamp")
    title_text = match.group("title")
    raw_title = clean_song_title(title_text)
    normalized_title = normalize_song_title(raw_title)
    has_setlist_number = line_has_setlist_number(line, title_text)
    if not is_probable_song_title(raw_title, normalized_title, has_setlist_number):
        return None

    try:
        seconds = timestamp_to_seconds(timestamp_text)
    except ValueError:
        return None

    return TimelineEntry(
        timestamp_text=timestamp_text,
        seconds=seconds,
        raw_song_title=raw_title,
        normalized_song_title=normalized_title,
    )


def is_blank_or_decoration(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return bool(re.fullmatch(r"[-=*_~\s\u30fb\u30fc\u2010-\u2015]+", stripped))


def timeline_span(entries: list[TimelineEntry]) -> int:
    if len(entries) < 2:
        return 0
    return max(entry.seconds for entry in entries) - min(entry.seconds for entry in entries)


def score_timeline_candidate(entries: list[TimelineEntry], has_marker: bool) -> int:
    marker_bonus = 1000 if has_marker else 0
    artist_lines = sum(1 for entry in entries if ARTIST_SEPARATOR_RE.search(entry.raw_song_title))
    return marker_bonus + len(entries) * 20 + artist_lines * 3 + min(timeline_span(entries) // 600, 20)
