"""SQLAlchemy models.

Every model must be imported here. Alembic compares the database against
Base.metadata to generate migrations, and a model that is never imported is
absent from that metadata — so autogenerate would emit a migration dropping
its table.
"""

from app.models.achievement_rule import AchievementRule
from app.models.announcement import AnnouncementDelivery, AnnouncementDestination
from app.models.audit_log import AuditLog
from app.models.celebration_replay import CelebrationReplay
from app.models.display_preview import DisplayPreview
from app.models.feed import FeedComment, FeedReaction
from app.models.channel import Channel, ChannelScreen, ChannelScreenBoard
from app.models.base import Base, TimestampMixin
from app.models.competition import Competition, CompetitionParticipant
from app.models.data_source import (
    ConnectorCredential,
    DataSource,
    SourceMapping,
    SyncRun,
    UserIdentity,
    WebhookEvent,
)
from app.models.directory import DirectoryPerson, DirectoryRule, DirectoryRun
from app.models.display import Display
from app.models.display_pairing import DisplayPairing
from app.models.game_token import GameToken
from app.models.goal import Goal
from app.models.leaderboard import Leaderboard
from app.models.login_attempt import LoginAttempt
from app.models.m365 import M365Link, M365Member, M365Source, MirrorPlacement
from app.models.metric_definition import MetricDefinition
from app.models.metric_fact import MetricFact
from app.models.background_library import SavedBackground
from app.models.badge import Badge, BadgeAward
from app.models.points import PointAward, PointValue
from app.models.report_schedule import ReportSchedule
from app.models.custom_role import CustomRole
from app.models.audit_stream import AuditStream
from app.models.season import Season
from app.models.tier import Tier
from app.models.unlock import Unlock, Unlockable
from app.models.wheel import PrizeWheel, WheelPrize, WheelSpin
from app.models.notification import Notification
from app.models.dismissal import Dismissal
from app.models.hosting_config import HostingConfig
from app.models.tv_announcement import TvAnnouncement, TvAnnouncementSend
from app.models.notification_preference import NotificationPreference
from app.models.office import Office
from app.models.organization import Organization
from app.models.session import Session
from app.models.oauth_client import OauthClient
from app.models.warehouse_connection import WarehouseConnection
from app.models.smtp_config import SmtpConfig
from app.models.sso_config import SsoConfig
from app.models.team import Team
from app.models.stored_asset import StoredAsset
from app.models.user import UserAccount
from app.models.user_token import UserToken
from app.models.walkup_media import WalkupMedia

__all__ = [
    "AchievementRule",
    "AnnouncementDelivery",
    "AnnouncementDestination",
    "AuditLog",
    "Badge",
    "BadgeAward",
    "CelebrationReplay",
    "DisplayPreview",
    "FeedComment",
    "FeedReaction",
    "Channel",
    "ChannelScreen",
    "ChannelScreenBoard",
    "Base",
    "Competition",
    "CompetitionParticipant",
    "ConnectorCredential",
    "DataSource",
    "Display",
    "DisplayPairing",
    "GameToken",
    "Goal",
    "Leaderboard",
    "LoginAttempt",
    "M365Link",
    "M365Member",
    "M365Source",
    "MetricDefinition",
    "MirrorPlacement",
    "MetricFact",
    "Notification",
    "Dismissal",
    "HostingConfig",
    "TvAnnouncement",
    "TvAnnouncementSend",
    "NotificationPreference",
    "Office",
    "PointAward",
    "PointValue",
    "ReportSchedule",
    "CustomRole",
    "AuditStream",
    "PrizeWheel",
    "Organization",
    "SavedBackground",
    "Season",
    "Session",
    "SourceMapping",
    "OauthClient",
    "WarehouseConnection",
    "DirectoryPerson",
    "DirectoryRule",
    "DirectoryRun",
    "SmtpConfig",
    "SsoConfig",
    "StoredAsset",
    "SyncRun",
    "Team",
    "Tier",
    "Unlock",
    "Unlockable",
    "TimestampMixin",
    "UserAccount",
    "UserIdentity",
    "UserToken",
    "WalkupMedia",
    "WebhookEvent",
    "WheelPrize",
    "WheelSpin",
]
