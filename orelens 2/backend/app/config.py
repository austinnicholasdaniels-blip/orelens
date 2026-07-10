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
    resend_api_key: str = ""       # enables digest email sending (RESEND_API_KEY)
    stripe_payment_link: str = (   # Stripe Payment Link (STRIPE_PAYMENT_LINK overrides)
        "https://buy.stripe.com/4gM6oIa5x3U41Om7Gb9AA00")
    stripe_webhook_secret: str = ""  # Stripe webhook signing secret (STRIPE_WEBHOOK_SECRET)
    session_secret: str = ""       # signs login session tokens (SESSION_SECRET)
    anthropic_api_key: str = ""    # powers The Assayer (ANTHROPIC_API_KEY)
    assayer_model: str = "claude-sonnet-4-6"
    digest_from: str = "OreLens <login@getorelens.com>"
    eodhd_api_key: str = ""        # EODHD All-In-One: prices, fundamentals, news
    admin_key: str = ""            # locks /api/admin/* when set (ADMIN_KEY env)
    resend_api_key: str = ""       # enables digest email sending (RESEND_API_KEY)
    stripe_payment_link: str = (   # Stripe Payment Link (STRIPE_PAYMENT_LINK overrides)
        "https://buy.stripe.com/4gM6oIa5x3U41Om7Gb9AA00")
    stripe_webhook_secret: str = ""  # Stripe webhook signing secret (STRIPE_WEBHOOK_SECRET)
    session_secret: str = ""       # signs login session tokens (SESSION_SECRET)
    anthropic_api_key: str = ""    # powers The Assayer (ANTHROPIC_API_KEY)
    assayer_model: str = "claude-sonnet-4-6"
    digest_from: str = "OreLens <login@getorelens.com>"
    cost_per_meter_default: float = 250.0  # CAD, all-in diamond drilling default
    class Config:
        env_file = ".env"

settings = Settings()
