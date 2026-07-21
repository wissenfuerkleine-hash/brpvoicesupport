"""
Custom AI Moderation Engine
Analyzes messages using multiple algorithms without any external API.
Produces: risk_score (0-100), trust_impact, severity (0-4), flags, reasoning, recommended_action.
"""

import re
import math
import time
import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Toxic word lists (multilingual core set)
# ---------------------------------------------------------------------------

TOXIC_WORDS: set = {
    "idiot", "stupid", "moron", "dumb", "retard", "retarded", "imbecile",
    "asshole", "bastard", "bitch", "cunt", "dick", "fuck", "fucking", "shit",
    "damn", "hell", "piss", "cock", "pussy", "whore", "slut", "faggot", "fag",
    "nigger", "nigga", "kike", "spic", "chink", "gook", "towelhead", "wetback",
    "nazi", "kill yourself", "kys", "die", "rape", "rapist",
    # German toxic words
    "idiot", "trottel", "arschloch", "scheiße", "scheiß", "hurensohn",
    "wichser", "fotze", "nutte", "schwuchtel", "neger", "spast",
}

DISCRIMINATION_WORDS: set = {
    "gay", "lesbian", "tranny", "trannies", "homo", "dyke",
    "feminist", "sjw", "libtard", "snowflake",
    "jew", "jewish", "muslim", "christian", "catholic",
    "black", "white", "asian", "hispanic", "arab",
}

SCAM_PATTERNS: List[str] = [
    r"free\s+(nitro|steam|gift|robux|vbucks)",
    r"click\s+(here|this)\s+(for|to\s+get)",
    r"discord\s*nitro\s*giveaway",
    r"claim\s+your\s+(free|prize|reward)",
    r"you\s+(have\s+been\s+selected|won|are\s+the\s+winner)",
    r"limited\s+time\s+offer",
    r"earn\s+\$?\d+\s+(a\s+day|per\s+day|daily|weekly)",
    r"work\s+from\s+home",
    r"crypto\s+(investment|profit|gain)",
    r"double\s+your\s+(bitcoin|eth|money)",
    r"\.gift/",
    r"discord\.gift",
    r"steamcommunity\.gift",
    r"invest(ment)?\s+opportunity",
    r"passwor[dt]",
    r"verify\s+your\s+account",
    r"account\s+suspended",
    r"login\s+required",
]

PHISHING_DOMAINS: set = {
    "discord-nitro.com", "discordapp.gift", "discord.gift.com",
    "steamcommunity.gift", "free-nitro.com", "discordnitro.net",
    "free-steam.com", "steam-trade.com", "roblox-free.com",
    "bit.ly", "tinyurl.com", "shorturl.at", "is.gd", "t.co",
    "grabify.link", "iplogger.org", "2no.co", "yip.su",
}

DISCORD_INVITE_PATTERN = re.compile(
    r"(discord\.gg|discord\.com/invite|discordapp\.com/invite)/[a-zA-Z0-9]+",
    re.IGNORECASE,
)

URL_PATTERN = re.compile(
    r"https?://[^\s]+|www\.[^\s]+",
    re.IGNORECASE,
)

MENTION_PATTERN = re.compile(r"<@[!&]?\d+>")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    risk_score: float = 0.0
    trust_impact: float = 0.0
    severity: int = 0
    flags: List[str] = field(default_factory=list)
    reasoning: str = ""
    recommended_action: str = "none"
    scores_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class UserContext:
    user_id: int
    guild_id: int
    trust_score: float = 100.0
    recent_messages: deque = field(default_factory=lambda: deque(maxlen=50))
    recent_timestamps: deque = field(default_factory=lambda: deque(maxlen=100))
    warning_count: int = 0
    timeout_count: int = 0
    account_age_days: int = 365
    join_age_days: int = 30


# ---------------------------------------------------------------------------
# Per-guild context cache (in-memory)
# ---------------------------------------------------------------------------

_guild_contexts: Dict[int, Dict[int, UserContext]] = defaultdict(dict)
_guild_join_timestamps: Dict[int, deque] = defaultdict(lambda: deque(maxlen=500))


def get_user_context(guild_id: int, user_id: int) -> UserContext:
    if user_id not in _guild_contexts[guild_id]:
        _guild_contexts[guild_id][user_id] = UserContext(
            user_id=user_id,
            guild_id=guild_id,
        )
    return _guild_contexts[guild_id][user_id]


def update_user_context(ctx: UserContext, content: str):
    now = time.time()
    ctx.recent_messages.append(content)
    ctx.recent_timestamps.append(now)


def record_guild_join(guild_id: int):
    _guild_join_timestamps[guild_id].append(time.time())


# ---------------------------------------------------------------------------
# Individual analysis functions
# ---------------------------------------------------------------------------

def _analyze_spam(content: str, ctx: UserContext, window: int = 10) -> Tuple[float, List[str]]:
    """Detect message flooding."""
    score = 0.0
    flags = []
    now = time.time()
    recent = [t for t in ctx.recent_timestamps if now - t < window]
    count = len(recent)

    if count >= 8:
        score += 60.0
        flags.append(f"flood:{count}_msgs_in_{window}s")
    elif count >= 5:
        score += 35.0
        flags.append(f"fast_messages:{count}_in_{window}s")

    if ctx.recent_messages:
        last = list(ctx.recent_messages)
        duplicates = sum(1 for m in last[-10:] if m == content)
        if duplicates >= 4:
            score += 50.0
            flags.append(f"duplicate_spam:{duplicates}x")
        elif duplicates >= 2:
            score += 20.0
            flags.append(f"repeated_message:{duplicates}x")

    return min(score, 100.0), flags


def _analyze_caps(content: str) -> Tuple[float, List[str]]:
    """Detect excessive caps lock usage."""
    letters = [c for c in content if c.isalpha()]
    if len(letters) < 6:
        return 0.0, []
    caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if caps_ratio > 0.8 and len(content) > 10:
        return 25.0, [f"excessive_caps:{int(caps_ratio*100)}%"]
    if caps_ratio > 0.6 and len(content) > 20:
        return 10.0, [f"high_caps:{int(caps_ratio*100)}%"]
    return 0.0, []


def _analyze_emoji_spam(content: str) -> Tuple[float, List[str]]:
    """Detect excessive emoji usage."""
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
        "\U00002700-\U000027BF\U0001FA00-\U0001FA6F]+",
        flags=re.UNICODE,
    )
    emoji_matches = emoji_pattern.findall(content)
    emoji_count = sum(len(m) for m in emoji_matches)
    custom_emoji = len(re.findall(r"<a?:[a-zA-Z0-9_]+:\d+>", content))
    total = emoji_count + custom_emoji
    if total > 15:
        return 30.0, [f"emoji_spam:{total}_emojis"]
    if total > 8:
        return 15.0, [f"many_emojis:{total}"]
    return 0.0, []


def _analyze_char_spam(content: str) -> Tuple[float, List[str]]:
    """Detect character spam (e.g., aaaaaaaa)."""
    if not content:
        return 0.0, []
    runs = re.findall(r"(.)\1{4,}", content)
    if runs:
        max_run = max(len(re.search(r"(.)\1+", m).group(0) if re.search(r"(.)\1+", m) else "" for m in runs), default=0)
        if max_run >= 10:
            return 25.0, [f"char_spam:run_of_{max_run}"]
        if max_run >= 5:
            return 10.0, [f"repeated_chars:run_of_{max_run}"]
    return 0.0, []


def _analyze_toxic_language(content: str) -> Tuple[float, List[str]]:
    """Detect toxic, offensive, discriminatory language."""
    content_lower = content.lower()
    words = re.findall(r"\b\w+\b", content_lower)
    word_set = set(words)

    toxic_hits = word_set & TOXIC_WORDS
    disc_hits = word_set & DISCRIMINATION_WORDS

    score = 0.0
    flags = []

    # Check bigrams for phrases like "kill yourself"
    bigrams = {f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)}
    phrase_hits = bigrams & TOXIC_WORDS
    toxic_hits |= phrase_hits

    if toxic_hits:
        score += min(len(toxic_hits) * 20, 80.0)
        flags.append(f"toxic_language:{len(toxic_hits)}_terms")

    if disc_hits:
        score += min(len(disc_hits) * 10, 30.0)
        flags.append(f"potentially_discriminatory:{len(disc_hits)}_terms")

    return min(score, 100.0), flags


def _analyze_scam(content: str) -> Tuple[float, List[str]]:
    """Detect scam and phishing patterns."""
    content_lower = content.lower()
    score = 0.0
    flags = []
    hits = []
    for pattern in SCAM_PATTERNS:
        if re.search(pattern, content_lower):
            hits.append(pattern[:30])
    if hits:
        score += min(len(hits) * 25, 85.0)
        flags.append(f"scam_pattern:{len(hits)}_matches")
    return score, flags


def _analyze_links(content: str) -> Tuple[float, List[str]]:
    """Detect phishing domains and suspicious links."""
    urls = URL_PATTERN.findall(content)
    score = 0.0
    flags = []
    if not urls:
        return 0.0, []

    import tldextract
    for url in urls:
        try:
            extracted = tldextract.extract(url)
            full_domain = f"{extracted.domain}.{extracted.suffix}".lower()
            if full_domain in PHISHING_DOMAINS:
                score += 70.0
                flags.append(f"phishing_domain:{full_domain}")
            elif extracted.suffix in {"xyz", "tk", "ml", "ga", "cf", "gq"}:
                score += 20.0
                flags.append(f"suspicious_tld:{extracted.suffix}")
        except Exception:
            pass

    if len(urls) > 3:
        score += 20.0
        flags.append(f"many_links:{len(urls)}")

    return min(score, 100.0), flags


def _analyze_discord_invites(content: str) -> Tuple[float, List[str]]:
    """Detect Discord invite links (advertising)."""
    invites = DISCORD_INVITE_PATTERN.findall(content)
    if invites:
        return 40.0, [f"discord_invite:{len(invites)}_links"]
    return 0.0, []


def _analyze_mass_ping(content: str) -> Tuple[float, List[str]]:
    """Detect mass mentioning."""
    mentions = MENTION_PATTERN.findall(content)
    everyone_here = len(re.findall(r"@(everyone|here)", content))
    total = len(mentions) + everyone_here * 3
    if total >= 10:
        return 60.0, [f"mass_ping:{total}_mentions"]
    if total >= 5:
        return 30.0, [f"multiple_pings:{total}_mentions"]
    if everyone_here:
        return 25.0, [f"everyone_here_ping:{everyone_here}x"]
    return 0.0, []


def _analyze_raid(guild_id: int) -> Tuple[float, List[str]]:
    """Detect potential raid (mass joins in short window)."""
    now = time.time()
    joins = _guild_join_timestamps.get(guild_id, deque())
    recent_joins = [t for t in joins if now - t < 60]
    if len(recent_joins) >= 10:
        return 80.0, [f"raid_detection:{len(recent_joins)}_joins_in_60s"]
    if len(recent_joins) >= 5:
        return 40.0, [f"suspicious_mass_join:{len(recent_joins)}_in_60s"]
    return 0.0, []


def _analyze_new_account(ctx: UserContext) -> Tuple[float, List[str]]:
    """Extra scrutiny for very new accounts."""
    score = 0.0
    flags = []
    if ctx.account_age_days < 1:
        score += 40.0
        flags.append("account_less_than_1_day_old")
    elif ctx.account_age_days < 7:
        score += 20.0
        flags.append(f"new_account:{ctx.account_age_days}days_old")
    if ctx.join_age_days < 1:
        score += 15.0
        flags.append("joined_server_less_than_1_day_ago")
    return score, flags


def _analyze_contextual_pattern(content: str, ctx: UserContext) -> Tuple[float, List[str]]:
    """Analyze patterns across recent messages for unusual behavior."""
    score = 0.0
    flags = []
    if len(ctx.recent_messages) < 3:
        return 0.0, []

    recent = list(ctx.recent_messages)[-10:]
    hashes = [hashlib.md5(m.encode()).hexdigest()[:8] for m in recent]
    unique_ratio = len(set(hashes)) / len(hashes)
    if unique_ratio < 0.3:
        score += 30.0
        flags.append(f"low_message_variety:{int(unique_ratio*100)}%_unique")

    avg_len = sum(len(m) for m in recent) / len(recent)
    if avg_len < 5 and len(recent) >= 5:
        score += 15.0
        flags.append("very_short_messages_pattern")

    return score, flags


def _analyze_length(content: str) -> Tuple[float, List[str]]:
    """Flag extremely long messages."""
    if len(content) > 1800:
        return 10.0, [f"very_long_message:{len(content)}_chars"]
    return 0.0, []


# ---------------------------------------------------------------------------
# Trust score modifiers
# ---------------------------------------------------------------------------

def _trust_impact_from_flags(flags: List[str], risk_score: float) -> float:
    impact = 0.0
    for flag in flags:
        if flag.startswith("toxic") or flag.startswith("discriminat"):
            impact -= 8.0
        elif flag.startswith("scam") or flag.startswith("phishing"):
            impact -= 15.0
        elif flag.startswith("flood") or flag.startswith("duplicate"):
            impact -= 5.0
        elif flag.startswith("raid"):
            impact -= 20.0
        elif flag.startswith("mass_ping"):
            impact -= 6.0
        elif flag.startswith("discord_invite"):
            impact -= 4.0
    impact -= risk_score * 0.05
    return max(impact, -50.0)


# ---------------------------------------------------------------------------
# Severity and action mapping
# ---------------------------------------------------------------------------

def _determine_severity_and_action(
    risk_score: float,
    flags: List[str],
    ctx: UserContext,
) -> Tuple[int, str]:
    """
    Severity 0 → none
    Severity 1 → warn
    Severity 2 → delete + timeout (10 min)
    Severity 3 → longer timeout (1 hour) + log + notify mod
    Severity 4 → perma mute until admin handles it
    """
    has_raid = any(f.startswith("raid") for f in flags)
    has_scam = any(f.startswith("scam") or f.startswith("phishing") for f in flags)
    has_toxic = any(f.startswith("toxic") for f in flags)

    if risk_score >= 80 or has_raid or ctx.timeout_count >= 5:
        return 4, "perma_mute"
    elif risk_score >= 60 or has_scam or ctx.warning_count >= 5:
        return 3, "long_timeout"
    elif risk_score >= 35 or has_toxic or ctx.warning_count >= 3:
        return 2, "delete_timeout"
    elif risk_score >= 15:
        return 1, "warn"
    return 0, "none"


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_message(
    content: str,
    user_id: int,
    guild_id: int,
    account_age_days: int = 365,
    join_age_days: int = 30,
    trust_score: float = 100.0,
    warning_count: int = 0,
    timeout_count: int = 0,
) -> AnalysisResult:
    """
    Full analysis of a single message.
    Returns AnalysisResult with all fields populated.
    """
    ctx = get_user_context(guild_id, user_id)
    ctx.trust_score = trust_score
    ctx.account_age_days = account_age_days
    ctx.join_age_days = join_age_days
    ctx.warning_count = warning_count
    ctx.timeout_count = timeout_count

    if not content or not content.strip():
        update_user_context(ctx, content or "")
        return AnalysisResult(recommended_action="none")

    all_flags: List[str] = []
    breakdown: Dict[str, float] = {}

    checks = [
        ("spam", _analyze_spam(content, ctx)),
        ("caps", _analyze_caps(content)),
        ("emoji_spam", _analyze_emoji_spam(content)),
        ("char_spam", _analyze_char_spam(content)),
        ("toxic", _analyze_toxic_language(content)),
        ("scam", _analyze_scam(content)),
        ("links", _analyze_links(content)),
        ("invites", _analyze_discord_invites(content)),
        ("mass_ping", _analyze_mass_ping(content)),
        ("raid", _analyze_raid(guild_id)),
        ("new_account", _analyze_new_account(ctx)),
        ("context", _analyze_contextual_pattern(content, ctx)),
        ("length", _analyze_length(content)),
    ]

    weighted_scores = {
        "spam": 1.5,
        "caps": 0.6,
        "emoji_spam": 0.5,
        "char_spam": 0.5,
        "toxic": 1.8,
        "scam": 2.0,
        "links": 1.5,
        "invites": 1.0,
        "mass_ping": 1.4,
        "raid": 2.0,
        "new_account": 0.7,
        "context": 0.8,
        "length": 0.3,
    }

    raw_total = 0.0
    weight_sum = 0.0
    for name, (score, flags) in checks:
        w = weighted_scores.get(name, 1.0)
        breakdown[name] = round(score, 2)
        all_flags.extend(flags)
        raw_total += score * w
        weight_sum += w

    risk_score = min((raw_total / weight_sum) if weight_sum > 0 else 0, 100.0)

    # Trust score adjustment: low trust raises risk slightly
    trust_modifier = max(0.0, (100.0 - trust_score) * 0.15)
    risk_score = min(risk_score + trust_modifier, 100.0)

    risk_score = round(risk_score, 2)
    trust_impact = round(_trust_impact_from_flags(all_flags, risk_score), 2)
    severity, action = _determine_severity_and_action(risk_score, all_flags, ctx)

    reasoning_parts = []
    if all_flags:
        reasoning_parts.append(f"Detected: {', '.join(all_flags[:6])}")
    reasoning_parts.append(f"Risk score: {risk_score}/100")
    reasoning_parts.append(f"Trust: {trust_score:.1f} → {max(0, trust_score + trust_impact):.1f}")
    if warning_count:
        reasoning_parts.append(f"User has {warning_count} prior warning(s)")
    reasoning = ". ".join(reasoning_parts)

    update_user_context(ctx, content)

    return AnalysisResult(
        risk_score=risk_score,
        trust_impact=trust_impact,
        severity=severity,
        flags=all_flags,
        reasoning=reasoning,
        recommended_action=action,
        scores_breakdown=breakdown,
    )


def analyze_join_event(guild_id: int, account_age_days: int, join_history: List[float]) -> AnalysisResult:
    """Analyze a member join event for raid detection."""
    record_guild_join(guild_id)
    flags = []
    score = 0.0

    now = time.time()
    recent_60 = [t for t in _guild_join_timestamps[guild_id] if now - t < 60]
    if len(recent_60) >= 10:
        score = 85.0
        flags.append(f"raid:{len(recent_60)}_joins_in_60s")
    elif len(recent_60) >= 5:
        score = 45.0
        flags.append(f"mass_join:{len(recent_60)}_in_60s")

    if account_age_days < 1:
        score += 30.0
        flags.append("brand_new_account")
    elif account_age_days < 7:
        score += 15.0
        flags.append(f"new_account:{account_age_days}d")

    severity = 0
    action = "none"
    if score >= 70:
        severity = 4
        action = "perma_mute"
    elif score >= 40:
        severity = 2
        action = "delete_timeout"

    return AnalysisResult(
        risk_score=min(score, 100.0),
        trust_impact=-score * 0.3,
        severity=severity,
        flags=flags,
        reasoning=f"Join event analysis: {', '.join(flags) if flags else 'normal'}",
        recommended_action=action,
        scores_breakdown={"join_score": score},
    )
