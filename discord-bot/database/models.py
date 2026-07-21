from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, Float, Text,
    DateTime, ForeignKey, JSON, Enum as SAEnum, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database.connection import Base
import enum


class SeverityLevel(enum.IntEnum):
    NONE = 0
    WARNING = 1
    DELETE_TIMEOUT = 2
    LONG_TIMEOUT = 3
    PERMA_MUTE = 4


class ActionType(str, enum.Enum):
    NONE = "none"
    WARN = "warn"
    DELETE = "delete"
    TIMEOUT = "timeout"
    LONG_TIMEOUT = "long_timeout"
    PERMA_MUTE = "perma_mute"
    UNBAN = "unban"
    UNMUTE = "unmute"
    KICK = "kick"
    BAN = "ban"
    ROLE_ADD = "role_add"
    ROLE_REMOVE = "role_remove"
    MESSAGE_DELETE = "message_delete"
    CHANNEL_CREATE = "channel_create"
    CHANNEL_DELETE = "channel_delete"


class Guild(Base):
    __tablename__ = "guilds"

    id = Column(BigInteger, primary_key=True)
    name = Column(String(100), nullable=False)
    icon_url = Column(String(512), nullable=True)
    owner_id = Column(BigInteger, nullable=True)
    member_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    settings = Column(JSON, default=dict)

    users = relationship("User", back_populates="guild")
    channels = relationship("Channel", back_populates="guild")
    logs = relationship("AuditLog", back_populates="guild")
    warnings = relationship("Warning", back_populates="guild")
    stats = relationship("ServerStats", back_populates="guild")
    dashboard_settings = relationship("DashboardSettings", back_populates="guild", uselist=False)


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=False)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    username = Column(String(100), nullable=False)
    discriminator = Column(String(10), default="0")
    display_name = Column(String(100), nullable=True)
    avatar_url = Column(String(512), nullable=True)
    is_bot = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    is_muted = Column(Boolean, default=False)
    is_perma_muted = Column(Boolean, default=False)
    trust_score = Column(Float, default=100.0)
    risk_score = Column(Float, default=0.0)
    message_count = Column(BigInteger, default=0)
    voice_minutes = Column(BigInteger, default=0)
    warning_count = Column(Integer, default=0)
    timeout_count = Column(Integer, default=0)
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    join_date = Column(DateTime(timezone=True), nullable=True)
    leave_date = Column(DateTime(timezone=True), nullable=True)
    roles = Column(JSON, default=list)
    notes = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("id", "guild_id", name="uq_user_guild"),
        Index("ix_users_guild_id", "guild_id"),
        Index("ix_users_trust_score", "trust_score"),
    )

    guild = relationship("Guild", back_populates="users")
    warnings = relationship("Warning", back_populates="user", foreign_keys="Warning.user_id")
    timeouts = relationship("Timeout", back_populates="user", foreign_keys="Timeout.user_id")
    bans = relationship("Ban", back_populates="user", foreign_keys="Ban.user_id")
    messages = relationship("Message", back_populates="user")
    voice_sessions = relationship("VoiceSession", back_populates="user")
    ai_analyses = relationship("AIAnalysis", back_populates="user")
    risk_records = relationship("RiskRecord", back_populates="user")


class Channel(Base):
    __tablename__ = "channels"

    id = Column(BigInteger, primary_key=True, autoincrement=False)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    channel_type = Column(String(50), default="text")
    category_id = Column(BigInteger, nullable=True)
    category_name = Column(String(100), nullable=True)
    is_nsfw = Column(Boolean, default=False)
    position = Column(Integer, default=0)
    message_count = Column(BigInteger, default=0)
    is_monitored = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (Index("ix_channels_guild_id", "guild_id"),)

    guild = relationship("Guild", back_populates="channels")
    messages = relationship("Message", back_populates="channel")


class Message(Base):
    __tablename__ = "messages"

    id = Column(BigInteger, primary_key=True, autoincrement=False)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id = Column(BigInteger, ForeignKey("channels.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    content = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=True)
    attachment_count = Column(Integer, default=0)
    embed_count = Column(Integer, default=0)
    mention_count = Column(Integer, default=0)
    is_deleted = Column(Boolean, default=False)
    is_edited = Column(Boolean, default=False)
    was_flagged = Column(Boolean, default=False)
    risk_score = Column(Float, default=0.0)
    severity = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    edited_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_messages_guild_id", "guild_id"),
        Index("ix_messages_user_id", "user_id"),
        Index("ix_messages_channel_id", "channel_id"),
        Index("ix_messages_created_at", "created_at"),
    )

    guild = relationship("Guild")
    channel = relationship("Channel", back_populates="messages")
    user = relationship("User", back_populates="messages")
    ai_analysis = relationship("AIAnalysis", back_populates="message", uselist=False)


class Warning(Base):
    __tablename__ = "warnings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    moderator_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=False)
    ai_generated = Column(Boolean, default=False)
    risk_score = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_warnings_user_guild", "user_id", "guild_id"),)

    guild = relationship("Guild", back_populates="warnings")
    user = relationship("User", back_populates="warnings", foreign_keys=[user_id])
    moderator = relationship("User", foreign_keys=[moderator_id])


class Timeout(Base):
    __tablename__ = "timeouts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    moderator_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    duration_seconds = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    ai_generated = Column(Boolean, default=False)
    risk_score = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_timeouts_user_guild", "user_id", "guild_id"),)

    user = relationship("User", back_populates="timeouts", foreign_keys=[user_id])
    moderator = relationship("User", foreign_keys=[moderator_id])


class Ban(Base):
    __tablename__ = "bans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    moderator_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    unbanned_at = Column(DateTime(timezone=True), nullable=True)
    unban_reason = Column(Text, nullable=True)

    user = relationship("User", back_populates="bans", foreign_keys=[user_id])
    moderator = relationship("User", foreign_keys=[moderator_id])


class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel_id = Column(BigInteger, nullable=True)
    channel_name = Column(String(100), nullable=True)
    joined_at = Column(DateTime(timezone=True), nullable=False)
    left_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, default=0)
    was_muted = Column(Boolean, default=False)
    was_deafened = Column(Boolean, default=False)
    was_streaming = Column(Boolean, default=False)

    __table_args__ = (Index("ix_voice_sessions_user_guild", "user_id", "guild_id"),)

    user = relationship("User", back_populates="voice_sessions")


class AIAnalysis(Base):
    __tablename__ = "ai_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(BigInteger, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    risk_score = Column(Float, default=0.0)
    trust_impact = Column(Float, default=0.0)
    severity = Column(Integer, default=0)
    flags = Column(JSON, default=list)
    reasoning = Column(Text, nullable=True)
    recommended_action = Column(String(50), nullable=True)
    action_taken = Column(String(50), nullable=True)
    scores_breakdown = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_ai_analyses_user_guild", "user_id", "guild_id"),)

    user = relationship("User", back_populates="ai_analyses")
    message = relationship("Message", back_populates="ai_analysis")


class RiskRecord(Base):
    __tablename__ = "risk_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    risk_score = Column(Float, default=0.0)
    trust_score = Column(Float, default=100.0)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_risk_records_user_guild", "user_id", "guild_id"),)

    user = relationship("User", back_populates="risk_records")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, nullable=True)
    username = Column(String(100), nullable=True)
    moderator_id = Column(BigInteger, nullable=True)
    moderator_name = Column(String(100), nullable=True)
    action = Column(String(100), nullable=False)
    channel_id = Column(BigInteger, nullable=True)
    channel_name = Column(String(100), nullable=True)
    message_id = Column(BigInteger, nullable=True)
    message_content = Column(Text, nullable=True)
    risk_score = Column(Float, nullable=True)
    trust_score = Column(Float, nullable=True)
    severity = Column(Integer, default=0)
    ai_reasoning = Column(Text, nullable=True)
    extra_data = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_audit_logs_guild_id", "guild_id"),
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    guild = relationship("Guild", back_populates="logs")


class ServerStats(Base):
    __tablename__ = "server_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    period = Column(String(20), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    messages_count = Column(BigInteger, default=0)
    unique_users = Column(Integer, default=0)
    new_members = Column(Integer, default=0)
    left_members = Column(Integer, default=0)
    warnings_issued = Column(Integer, default=0)
    timeouts_issued = Column(Integer, default=0)
    bans_issued = Column(Integer, default=0)
    ai_flags = Column(Integer, default=0)
    voice_minutes = Column(BigInteger, default=0)
    top_channels = Column(JSON, default=list)
    top_users = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("guild_id", "period", "period_start", name="uq_server_stats_period"),
        Index("ix_server_stats_guild_period", "guild_id", "period"),
    )

    guild = relationship("Guild", back_populates="stats")


class DashboardSettings(Base):
    __tablename__ = "dashboard_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, unique=True)
    log_channel_id = Column(BigInteger, nullable=True)
    alert_channel_id = Column(BigInteger, nullable=True)
    mod_channel_id = Column(BigInteger, nullable=True)
    auto_moderation = Column(Boolean, default=True)
    raid_protection = Column(Boolean, default=True)
    spam_protection = Column(Boolean, default=True)
    link_filter = Column(Boolean, default=True)
    invite_filter = Column(Boolean, default=True)
    caps_filter = Column(Boolean, default=True)
    mention_limit = Column(Integer, default=5)
    message_rate_limit = Column(Integer, default=5)
    message_rate_window = Column(Integer, default=5)
    min_account_age_days = Column(Integer, default=7)
    warn_threshold = Column(Integer, default=3)
    timeout_threshold = Column(Integer, default=5)
    perma_mute_threshold = Column(Integer, default=8)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    guild = relationship("Guild", back_populates="dashboard_settings")


class Moderator(Base):
    __tablename__ = "moderators"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    username = Column(String(100), nullable=False)
    api_token_hash = Column(String(256), nullable=True)
    is_admin = Column(Boolean, default=False)
    actions_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("guild_id", "user_id", name="uq_moderator_guild"),)
