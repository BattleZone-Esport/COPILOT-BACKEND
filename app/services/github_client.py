
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.core.http_client import get_http_client

_logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, http_client: httpx.AsyncClient):
        s = get_settings()
        self.http_client = http_client
        self.token = s.GITHUB_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }

    async def _request(self, method: str, url: str, **kwargs) -> dict[str, Any]:
        _logger.debug(f"Request: {method} {url}")
        res = await self.http_client.request(method, url, headers=self.headers, **kwargs)
        res.raise_for_status()
        return res.json()

    async def get_repo_details(self, repo_name: str) -> dict[str, Any]:
        url = f"https://api.github.com/repos/{repo_name}"
        return await self._request("GET", url)

    async def get_latest_commit(self, repo_name: str, branch: str) -> dict[str, Any]:
        url = f"https://api.github.com/repos/{repo_name}/commits/{branch}"
        return await self._request("GET", url)

    async def create_branch(self, repo_name: str, new_branch: str, base_branch: str) -> None:
        latest_commit = await self.get_latest_commit(repo_name, base_branch)
        sha = latest_commit["sha"]
        url = f"https://api.github.com/repos/{repo_name}/git/refs"
        data = {"ref": f"refs/heads/{new_branch}", "sha": sha}
        await self._request("POST", url, json=data)

    async def get_file_content(self, repo_name: str, file_path: str, branch: str) -> Optional[dict[str, Any]]:
        url = f"https://api.github.com/repos/{repo_name}/contents/{file_path}?ref={branch}"
        try:
            return await self._request("GET", url)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def create_or_update_file(
        self, repo_name: str, file_path: str, content: str, branch: str, commit_message: str
    ) -> None:
        url = f"https://api.github.com/repos/{repo_name}/contents/{file_path}"
        data: dict[str, Any] = {
            "message": commit_message,
            "content": content,
            "branch": branch,
        }
        existing_file = await self.get_file_content(repo_name, file_path, branch)
        if existing_file:
            data["sha"] = existing_file["sha"]

        await self._request("PUT", url, json=data)

    async def create_pull_request(
        self, repo_name: str, title: str, head: str, base: str, body: str = ""
    ) -> dict[str, Any]:
        url = f"https://api.github.com/repos/{repo_name}/pulls"
        data = {"title": title, "head": head, "base": base, "body": body}
        return await self._request("POST", url, json=data)


async def get_github_client(
    http_client: httpx.AsyncClient = await get_http_client(),
) -> GitHubClient:
    return GitHubClient(http_client)
