"""Strict, centralized Railway environment configuration."""
from __future__ import annotations

from functools import cached_property
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file=".env", env_file_encoding="utf-8")

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    admin_ids: str = Field(alias="ADMIN_IDS")
    owner_ids: str = Field(default="", alias="OWNER_IDS")
    webhook_url: str = Field(alias="WEBHOOK_URL")
    webhook_secret: str = Field(alias="WEBHOOK_SECRET")
    target_chat_id: int | None = Field(default=None, alias="TARGET_CHAT_ID")
    target_user_id: int | None = Field(default=None, alias="TARGET_USER_ID")
    target_username: str | None = Field(default=None, alias="TARGET_USERNAME")
    demo_contact_username: str | None = Field(default=None, alias="DEMO_CONTACT_USERNAME")
    port: int = Field(default=8080, ge=1, le=65535, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    default_stars: int = Field(default=1000, ge=1, le=10**12, alias="DEFAULT_STARS")
    default_expiration: int = Field(default=30, ge=1, le=10080, alias="DEFAULT_EXPIRATION")
    default_gift_url: str = Field(default="https://t.me/nft/Example-1", alias="DEFAULT_GIFT_URL")
    default_gift_name: str = Field(default="NFT Gift", alias="DEFAULT_GIFT_NAME")
    default_image_path: str = Field(default="app/assets/fallback.png", alias="DEFAULT_IMAGE_PATH")
    expiration_sweep_seconds: int = Field(default=20, ge=5, le=300, alias="EXPIRATION_SWEEP_SECONDS")

    @field_validator("target_chat_id", "target_user_id", mode="before")
    @classmethod
    def empty_optional_id(cls, v):
        return None if v in (None, "") else v

    @field_validator("target_username", mode="before")
    @classmethod
    def normalized_username(cls, v):
        return (str(v).strip().lstrip("@").lower() or None) if v else None

    @field_validator("demo_contact_username", mode="before")
    @classmethod
    def valid_demo_contact(cls, v):
        import re
        if not v:
            return None
        s = str(v).strip().lstrip("@").lower()
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", s):
            raise ValueError("DEMO_CONTACT_USERNAME: username из 5–32 латинских букв, цифр или _")
        return s

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            return "postgresql+psycopg://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            return "postgresql+psycopg://" + v[len("postgresql://"):]
        if v.startswith(("postgresql+psycopg://", "sqlite://")):
            return v
        raise ValueError("DATABASE_URL должен быть postgres://, postgresql:// или postgresql+psycopg://")

    @field_validator("webhook_url")
    @classmethod
    def valid_webhook(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        s = urlsplit(v)
        if s.scheme != "https" or not s.netloc or s.query or s.fragment:
            raise ValueError("WEBHOOK_URL должен быть публичным HTTPS-URL без query и fragment")
        return v

    @field_validator("webhook_secret")
    @classmethod
    def valid_secret(cls, v: str) -> str:
        if len(v) < 24 or len(v) > 256 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in v):
            raise ValueError("WEBHOOK_SECRET: 24–256 символов [A-Za-z0-9_-]")
        return v

    @field_validator("default_image_path")
    @classmethod
    def validate_default_image(cls, v: str) -> str:
        from pathlib import Path
        f = Path(v)
        # Prevent leaking runtime environment files into Telegram via configurable uploads.
        assets = (Path(__file__).resolve().parent / "assets").resolve()
        resolved = (Path.cwd() / f).resolve()
        if not resolved.is_relative_to(assets) or resolved.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("DEFAULT_IMAGE_PATH должен указывать на изображение в app/assets/")
        if not resolved.is_file():
            raise ValueError("DEFAULT_IMAGE_PATH: изображение не найдено в Docker-проекте")
        return str(resolved)

    @field_validator("bot_token")
    @classmethod
    def valid_token(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", v):
            raise ValueError("BOT_TOKEN выглядит некорректно: получите токен у @BotFather")
        return v

    @staticmethod
    def parse_ids(raw: str) -> frozenset[int]:
        try:
            result = frozenset(int(i.strip()) for i in raw.split(",") if i.strip())
        except ValueError as e:
            raise ValueError("ADMIN_IDS / OWNER_IDS: только числовые Telegram ID через запятую") from e
        if any(v <= 0 for v in result):
            raise ValueError("Telegram IDs должны быть положительными числами")
        return result

    @model_validator(mode="after")
    def validate_role_owners(self):
        admins = self.parse_ids(self.admin_ids)
        if not admins:
            raise ValueError("Укажите хотя бы один ADMIN_IDS")
        owners = self.parse_ids(self.owner_ids) if self.owner_ids else {min(admins)}
        if not set(owners).issubset(admins):
            raise ValueError("OWNER_IDS должны входить в ADMIN_IDS")
        if self.target_chat_id is not None and self.target_chat_id <= 0:
            raise ValueError("TARGET_CHAT_ID для личного Business-чата должен быть положительным")
        if self.target_user_id is not None and self.target_user_id <= 0:
            raise ValueError("TARGET_USER_ID должен быть положительным")
        return self

    @property
    def admin_id_set(self) -> frozenset[int]:
        return self.parse_ids(self.admin_ids)

    @property
    def owner_id_set(self) -> frozenset[int]:
        return self.parse_ids(self.owner_ids) if self.owner_ids else frozenset({min(self.admin_id_set)})

    @property
    def webhook_endpoint(self) -> str:
        return self.webhook_url + "/telegram/webhook"
