from supabase import create_client, Client
from api.config import get_settings

_supabase: Client | None = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        settings = get_settings()
        _supabase = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase
