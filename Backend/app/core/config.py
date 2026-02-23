"""
Application configuration loaded from environment variables.

Uses pydantic-settings to validate and provide typed access to all config values.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────────
    APP_NAME: str = "AI-Assisted Exam Builder"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # ── Database (PostgreSQL + pgvector) ─────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/exam_builder"
    # Sync URL used by Alembic or one-off scripts
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://postgres:postgres@localhost:5433/exam_builder"

    # ── Redis ────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── LLM Provider ─────────────────────────────────────────────
    LLM_PROVIDER: str = "mock"  # "openai" | "ollama" | "mock"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3"

    # ── Embedding ────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    # ── Chunking ─────────────────────────────────────────────────
    CHUNK_SIZE: int = 3000
    CHUNK_OVERLAP: int = 400

    # ── File Storage ─────────────────────────────────────────────
    UPLOAD_DIR: str = "data/uploads"   # relative to the process cwd (Backend/)
    MAX_UPLOAD_SIZE_MB: int = 50       # hard limit enforced in the route

    # ── CORS ─────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


# Singleton – import this everywhere
settings = Settings()
