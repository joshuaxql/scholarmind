import httpx

from scholarmind.core.config import Settings


def build_provider_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
        limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
        headers={"User-Agent": f"{settings.app_name}/0.1"},
        follow_redirects=False,
    )
