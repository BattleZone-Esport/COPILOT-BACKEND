
import httpx

class AsyncHttpClient:
    _client = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None:
            cls._client = httpx.AsyncClient()
        return cls._client

def get_http_client() -> httpx.AsyncClient:
    return AsyncHttpClient.get_client()
