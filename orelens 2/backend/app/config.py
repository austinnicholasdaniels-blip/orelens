from pydantic import field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://orelens:orelens@localhost:5432/orelens"

    @field_validator("database_url")
    @classmethod
    def _normalize_pg(cls, v: str) -> str:
        # Render/Heroku hand out postgres:// URLs; SQLAlchemy wants postgresql+psycopg2://
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+psycopg2://", 1)
        return v
    fmp_api_key: str = ""          # Financial Modeling Prep
    polygon_api_key: str = ""      # optional alternative
    anthropic_api_key: str = ""    # for MD&A / financial statement extraction
    eodhd_api_key: str = ""        # EODHD All-In-One: prices, fundamentals, news
    admin_key: str = ""            # locks /api/admin/* when set (ADMIN_KEY env)
    eodhd_api_key: str = ""        # EODHD All-In-One: prices, fundamentals, news
    admin_key: str = ""            # locks /api/admin/* when set (ADMIN_KEY env)
    cost_per_meter_default: float = 250.0  # CAD, all-in diamond drilling default
    class Config:
        env_file = ".env"

settings = Settings()
