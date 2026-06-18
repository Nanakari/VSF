from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from timeline_parser import clean_song_title, normalize_song_title


SLASH_RE = re.compile(r"\s*[/\uff0f]\s*")
PIPE_RE = re.compile(r"\s*[|\uff5c]\s*")
DASH_RE = re.compile(r"\s+(?:-|\u2013|\u2014)\s+")
BRACKET_PREFIX_RE = re.compile(r"^\s*[\[\u3010\u300e\u300c\uff3b](.{1,50})[\]\u3011\u300f\u300d\uff3d]\s*(.+)$")
ARTIST_TOKEN_RE = re.compile(
    r"\s*(?:"
    r"\u00d7|[&\uff06]|\u30fb|\uff0b|\+|"
    r"\s+[xX]\s+|"
    r"\bw\s*[/\uff0f]\s*|\bfeat\.?\b|\bft\.?\b|\bwith\b|\band\b|"
    r"\bcovered\s+by\b|\bcover\s+by\b|"
    r"[/\uff0f]"
    r")\s*",
    re.IGNORECASE,
)

TRAILING_VERSION_RE = re.compile(
    r"\s*(?:-|\u2013|\u2014|\(|\uff08|\[|\uff3b)?\s*"
    r"(?:"
    r"(?:[a-z0-9' ]+\s+)?(?:piano|acoustic|guitar|live|karaoke|instrumental|remix|arrange|off\s*vocal)\s*"
    r"(?:ver\.?|version)?|"
    r"(?:piano|acoustic|guitar|live|karaoke|instrumental|remix|arrange|off\s*vocal)\s*"
    r"(?:ver\.?|version)?|"
    r"ver\.?|version|"
    r"\u30d4\u30a2\u30ce(?:ver\.?)?|\u30a2\u30b3\u30fc\u30b9\u30c6\u30a3\u30c3\u30af(?:ver\.?)?|"
    r"\u30ae\u30bf\u30fc(?:ver\.?)?|\u30a2\u30ec\u30f3\u30b8(?:ver\.?)?"
    r")\s*"
    r"(?:\)|\uff09|\]|\uff3d)?\s*$",
    re.IGNORECASE,
)

VERSION_MARKER_RE = re.compile(
    r"("
    r"\bacoustic\b|\bver\.?\b|\bversion\b|\barrange\b|\bremix\b|"
    r"\bthe\s+first\s+take\b|\bfrom\b|\blive\b|\binstrumental\b|"
    r"\boff\s*vocal\b|\bpiano\b|\bguitar\b|\bkaraoke\b|"
    r"\u30a2\u30b3\u30fc\u30b9\u30c6\u30a3\u30c3\u30af|"
    r"\u30d0\u30fc\u30b8\u30e7\u30f3|\u30d0\u30fc\u30b8\u30e7\u30f3|"
    r"\u30d4\u30a2\u30ce|\u30ae\u30bf\u30fc|\u30a2\u30ec\u30f3\u30b8"
    r")",
    re.IGNORECASE,
)

COMMON_ARTIST_KEYS = {
    "ado",
    "aimyon",
    "aimer",
    "kanaria",
    "kemu",
    "lisa",
    "minato",
    "n-buna",
    "n-buna".replace("-", ""),
    "orangestar",
    "supercell",
    "yoasobi",
    "yonezukenshi",
    "\u661f\u8857\u3059\u3044\u305b\u3044",
    "\u7c73\u6d25\u7384\u5e2b",
    "\u521d\u97f3\u30df\u30af",
}

AMBIGUOUS_STANDALONE_KEYS = {"encore", "\u30a2\u30f3\u30b3\u30fc\u30eb"}


@dataclass(frozen=True)
class ParsedSongIdentity:
    song_title: str
    artist_text: str
    artists: tuple[str, ...]
    artist_keys: tuple[str, ...]
    source: str
    ambiguous: bool = False

    @property
    def artist_group_key(self) -> str:
        return "|".join(sorted(set(self.artist_keys)))


def parse_song_identity(
    raw_title: str,
    known_artist_keys: set[str] | None = None,
) -> ParsedSongIdentity:
    original_title = raw_title.replace("\u3000", " ").strip()
    cleaned_title = clean_song_title(original_title)
    known_keys = set(COMMON_ARTIST_KEYS)
    if known_artist_keys:
        known_keys.update(known_artist_keys)

    bracket_match = BRACKET_PREFIX_RE.match(original_title)
    if bracket_match:
        artist_part = clean_song_title(bracket_match.group(1))
        song_part = clean_song_title(bracket_match.group(2))
        if song_part and is_likely_artist_text(artist_part):
            return make_identity(song_part, artist_part, "bracket")

    for pattern, source in ((SLASH_RE, "slash"), (PIPE_RE, "pipe")):
        parts = [part.strip() for part in pattern.split(cleaned_title, maxsplit=1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return make_identity(clean_song_title(parts[0]), clean_song_title(parts[1]), source)

    dash_parts = [part.strip() for part in DASH_RE.split(cleaned_title, maxsplit=1)]
    if len(dash_parts) == 2 and dash_parts[0] and dash_parts[1]:
        left, right = clean_song_title(dash_parts[0]), clean_song_title(dash_parts[1])
        left_key = compact_key(left)
        right_key = compact_key(right)
        if left_key in known_keys and not looks_like_version_note(right):
            return make_identity(right, left, "dash_artist_first")
        if right_key in known_keys and not looks_like_version_note(right):
            return make_identity(left, right, "dash_artist_last")
        if is_likely_artist_text(right) and not looks_like_version_note(right):
            return make_identity(left, right, "dash_artist_last")

    return make_identity(cleaned_title, "", "none")


def make_identity(song_title: str, artist_text: str, source: str) -> ParsedSongIdentity:
    cleaned_song = clean_song_title(song_title)
    cleaned_artist = clean_song_title(artist_text)
    artists = split_artist_tokens(cleaned_artist)
    artist_keys = tuple(sorted({compact_key(artist) for artist in artists if compact_key(artist)}))
    ambiguous = compact_key(cleaned_song) in AMBIGUOUS_STANDALONE_KEYS and not artist_keys
    return ParsedSongIdentity(
        song_title=cleaned_song,
        artist_text=cleaned_artist,
        artists=tuple(artists),
        artist_keys=artist_keys,
        source=source,
        ambiguous=ambiguous,
    )


def split_artist_tokens(artist_text: str) -> list[str]:
    if not artist_text:
        return []
    tokens = []
    for token in ARTIST_TOKEN_RE.split(artist_text):
        cleaned = clean_song_title(token)
        if cleaned and is_likely_artist_text(cleaned):
            tokens.append(cleaned)
    return tokens


def split_song_artist(raw_title: str) -> tuple[str, str]:
    parsed = parse_song_identity(raw_title)
    return parsed.song_title, parsed.artist_text


def song_merge_key(raw_title: str) -> str:
    return compact_key(canonical_song_title_for_merge(parse_song_identity(raw_title).song_title))


def artist_merge_key(raw_title: str) -> str:
    return parse_song_identity(raw_title).artist_group_key


def compact_key(value: str) -> str:
    normalized = normalize_song_title(value)
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def canonical_song_title_for_merge(song_title: str) -> str:
    title = clean_song_title(song_title)
    previous = None
    while previous != title:
        previous = title
        title = TRAILING_VERSION_RE.sub("", title).strip()
    return clean_song_title(title) or clean_song_title(song_title)


def artist_query_matches(artist_keys: set[str] | tuple[str, ...], query: str) -> bool:
    query_key = compact_key(query)
    if not query_key:
        return True
    keys = [key for key in artist_keys if key]
    if not keys:
        return False
    if query_key in keys:
        return True
    if is_short_ascii_key(query_key):
        return False
    return any(query_key in key or key in query_key for key in keys)


def is_likely_artist_text(value: str) -> bool:
    key = compact_key(value)
    if not key or len(key) < 2 or len(key) > 48:
        return False
    if key in AMBIGUOUS_STANDALONE_KEYS:
        return False
    if looks_like_version_note(value):
        return False
    if any(marker in value for marker in ("?", "\uff1f", "!", "\uff01")) and len(key) > 12:
        return False
    words = [word for word in re.split(r"\s+", value.strip()) if word]
    if len(words) > 5:
        return False
    return True


def looks_like_version_note(value: str) -> bool:
    return bool(VERSION_MARKER_RE.search(value))


def is_similar_song_key(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) < 6:
        return False
    distance = levenshtein_distance(left, right, max_distance=2)
    if distance > 2:
        return False
    return distance <= 1 or min(len(left), len(right)) >= 9


def levenshtein_distance(left: str, right: str, max_distance: int = 2) -> int:
    if abs(len(left) - len(right)) > max_distance:
        return max_distance + 1
    if len(left) > len(right):
        left, right = right, left

    previous = list(range(len(left) + 1))
    for index, right_char in enumerate(right, start=1):
        current = [index]
        row_min = current[0]
        for left_index, left_char in enumerate(left, start=1):
            insert_cost = current[left_index - 1] + 1
            delete_cost = previous[left_index] + 1
            replace_cost = previous[left_index - 1] + (left_char != right_char)
            value = min(insert_cost, delete_cost, replace_cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def choose_display_title(titles: list[str]) -> str:
    if not titles:
        return ""
    song_titles = [canonical_song_title_for_merge(split_song_artist(title)[0]) for title in titles]
    counts = Counter(song_titles)
    return sorted(
        counts.items(),
        key=lambda item: (-item[1], len(item[0]), reverse_text_key(item[0])),
    )[0][0]


def choose_display_artist(titles: list[str]) -> str:
    artists = [
        parsed.artists[0]
        for title in titles
        if (parsed := parse_song_identity(title)).artists
    ]
    if not artists:
        return ""
    counts = Counter(artists)
    return sorted(counts.items(), key=lambda item: (-item[1], len(item[0]), item[0].casefold()))[0][0]


def reverse_text_key(value: str) -> tuple[int, ...]:
    return tuple(-ord(char) for char in value.casefold())


def is_short_ascii_key(value: str) -> bool:
    return len(value) <= 4 and value.isascii() and value.isalnum()
