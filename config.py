import os
import json
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── Twilio ──────────────────────────────────────────────────────────────
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_phone_number: str = os.getenv("TWILIO_PHONE_NUMBER", "")

    # ── OpenAI ──────────────────────────────────────────────────────────────
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    # ── ElevenLabs ──────────────────────────────────────────────────────────
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")

    # ── Serveur ──────────────────────────────────────────────────────────────
    base_url: str = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./robot_rdv.db")
    timezone: str = os.getenv("TIMEZONE", "Europe/Paris")

    # ── Google Calendar ──────────────────────────────────────────────────────
    google_calendar_id: str = os.getenv("GOOGLE_CALENDAR_ID", "")
    google_credentials_file: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

    # ── Auth JWT ─────────────────────────────────────────────────────────────
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "change-me-in-production-please")
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30

    # ── Stripe ───────────────────────────────────────────────────────────────
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_publishable_key: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    stripe_price_id: str = os.getenv("STRIPE_PRICE_ID", "")
    stripe_trial_days: int = int(os.getenv("STRIPE_TRIAL_DAYS", "7"))
    stripe_trial_amount_cents: int = int(os.getenv("STRIPE_TRIAL_AMOUNT_CENTS", "3000"))  # 30€

    # ── Microsoft Azure (Outlook) ────────────────────────────────────────────
    azure_client_id: str = os.getenv("AZURE_CLIENT_ID", "")
    azure_client_secret: str = os.getenv("AZURE_CLIENT_SECRET", "")
    azure_tenant_id: str = os.getenv("AZURE_TENANT_ID", "common")

    # ── Mailgun ──────────────────────────────────────────────────────────────
    mailgun_api_key: str = os.getenv("MAILGUN_API_KEY", "")
    mailgun_domain: str = os.getenv("MAILGUN_DOMAIN", "")
    from_email: str = os.getenv("FROM_EMAIL", "noreply@robotrdv.fr")
    from_name: str = os.getenv("FROM_NAME", "AssistantAI")

    # ── Admin ────────────────────────────────────────────────────────────────
    admin_api_key: str = os.getenv("ADMIN_API_KEY", "change_me_in_env")

    # ── Tarifs des plans ─────────────────────────────────────────────────────
    plan_prices: dict = {"starter": 300.0, "pro": 300.0, "enterprise": 300.0}

    # ── Coûts API approximatifs (en EUR) ─────────────────────────────────────
    cost_gpt4o_input_per_1k: float = 0.0046     # ~$0.005 / 1k tokens
    cost_gpt4o_output_per_1k: float = 0.0138    # ~$0.015 / 1k tokens
    cost_elevenlabs_per_1k_chars: float = 0.276  # ~$0.30 / 1k chars
    cost_twilio_voice_per_min: float = 0.012     # ~$0.013 / min
    cost_twilio_sms: float = 0.007               # ~$0.0075 / SMS

    @property
    def google_calendar_enabled(self) -> bool:
        return bool(self.google_client_id) and bool(self.google_client_secret)

    @property
    def mailgun_enabled(self) -> bool:
        return bool(self.mailgun_api_key) and bool(self.mailgun_domain)

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key)

    @property
    def outlook_enabled(self) -> bool:
        return bool(self.azure_client_id) and bool(self.azure_client_secret)


settings = Settings()


def load_business_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "business_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)
