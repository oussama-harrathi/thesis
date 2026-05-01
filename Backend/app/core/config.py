"""
Application configuration loaded from environment variables.

Uses pydantic-settings to validate and provide typed access to all config values.
"""

import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_CORS_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:80",
    "http://127.0.0.1:80",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class Settings(BaseSettings):
    """Central application settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_NAME: str = "AI-Assisted Exam Builder"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # Database (PostgreSQL + pgvector)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/exam_builder"
    # Sync URL used by Alembic or one-off scripts
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://postgres:postgres@localhost:5433/exam_builder"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM Provider
    # Supported: openai_compatible | gemini | ollama | mock
    LLM_PROVIDER: str = "mock"

    # OpenAI-compatible provider (Groq / OpenRouter / OpenAI)
    OPENAI_COMPATIBLE_API_KEY: str = ""
    OPENAI_COMPATIBLE_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_COMPATIBLE_MODEL: str = "gpt-4o-mini"
    OPENAI_COMPATIBLE_TEMPERATURE: float = 0.3
    OPENAI_COMPATIBLE_MAX_TOKENS: int = 2048
    OPENAI_COMPATIBLE_TIMEOUT: float = 60.0

    # Fallback provider
    # When set, a failed primary call is retried using this provider.
    # Supported values: cerebras | gemini | openai_compatible | ollama | mock | "" (disabled)
    LLM_FALLBACK_PROVIDER: str = ""

    # Optional second fallback (tertiary). When set, the chain is:
    #   primary -> LLM_FALLBACK_PROVIDER -> LLM_SECOND_FALLBACK_PROVIDER
    LLM_SECOND_FALLBACK_PROVIDER: str = ""

    # Cerebras provider
    CEREBRAS_API_KEY: str = ""
    CEREBRAS_BASE_URL: str = "https://api.cerebras.ai/v1"
    CEREBRAS_MODEL: str = "llama3.1-8b"
    CEREBRAS_TEMPERATURE: float = 0.3
    CEREBRAS_MAX_TOKENS: int = 2048
    CEREBRAS_TIMEOUT: float = 60.0

    # Gemini provider
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"
    GEMINI_TEMPERATURE: float = 0.3
    GEMINI_MAX_TOKENS: int = 2048
    GEMINI_TIMEOUT: float = 60.0

    # Ollama provider
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3"
    OLLAMA_TEMPERATURE: float = 0.3
    OLLAMA_MAX_TOKENS: int = 2048
    OLLAMA_TIMEOUT: float = 120.0

    # Embedding
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    # Chunking
    CHUNK_SIZE: int = 1500
    CHUNK_OVERLAP: int = 200

    # Rate limiting
    # Tokens per minute sent to the LLM provider.
    # Groq free tier = 12 000 TPM; raise for paid tiers or other providers.
    # Set to 1_000_000 to effectively disable pacing.
    LLM_TPM_LIMIT: int = 12_000

    # File Storage
    UPLOAD_DIR: str = "data/uploads"   # relative to the process cwd (Backend/)
    MAX_UPLOAD_SIZE_MB: int = 50       # hard limit enforced in the route
    EXPORT_DIR: str = "data/exports"   # export output directory (relative to Backend/)

    # CORS
    CORS_ORIGINS: list[str] = DEFAULT_CORS_ORIGINS.copy()

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        """Accept JSON arrays or comma-separated origin strings from env vars."""
        if value is None:
            return DEFAULT_CORS_ORIGINS.copy()

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return DEFAULT_CORS_ORIGINS.copy()
            if raw == "*":
                return ["*"]
            if raw.startswith("["):
                value = json.loads(raw)
            else:
                value = raw.split(",")

        if not isinstance(value, (list, tuple, set)):
            msg = "CORS_ORIGINS must be a list, JSON array string, or comma-separated string"
            raise TypeError(msg)

        normalized: list[str] = []
        for origin in value:
            if not isinstance(origin, str):
                msg = "Each CORS origin must be a string"
                raise TypeError(msg)
            cleaned = origin.strip().rstrip("/")
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)

        return normalized or DEFAULT_CORS_ORIGINS.copy()

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value: object) -> bool | object:
        """Accept common environment labels such as 'release' or 'production'."""
        if isinstance(value, str):
            raw = value.strip().lower()
            if raw in {"release", "prod", "production"}:
                return False
            if raw in {"debug", "dev", "development"}:
                return True
        return value


# Singleton - import this everywhere
settings = Settings()
