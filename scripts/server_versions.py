# /// script
# dependencies = [
#   "httpx",
# ]
# ///

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx
import tomllib


async def get_latest_npm(client: httpx.AsyncClient, package: str) -> str:
    r = await client.get(f"https://registry.npmjs.org/{package}/latest")
    r.raise_for_status()
    return r.json()["version"]


async def get_latest_pypi(client: httpx.AsyncClient, package: str) -> str:
    r = await client.get(f"https://pypi.org/pypi/{package}/json")
    r.raise_for_status()
    return r.json()["info"]["version"]


async def get_latest_github_release(client: httpx.AsyncClient, repo: str) -> str:
    headers = {"User-Agent": "lsp-client-updater"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    r = await client.get(
        f"https://api.github.com/repos/{repo}/releases/latest", headers=headers
    )
    r.raise_for_status()
    return r.json()["tag_name"]


async def get_latest_custom(command: str) -> str:
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed: {stderr.decode().strip()}")
    return stdout.decode().strip()


async def fetch_version(
    client: httpx.AsyncClient, server: str, config: dict[str, Any]
) -> tuple[str, str | None]:
    try:
        t = config.get("type")
        if t == "npm":
            v = await get_latest_npm(client, config["package"])
        elif t == "pypi":
            v = await get_latest_pypi(client, config["package"])
        elif t == "github":
            v = await get_latest_github_release(client, config["repo"])
            if config.get("strip_v"):
                v = v.lstrip("v")
        elif t == "custom":
            v = await get_latest_custom(config["command"])
        else:
            return server, None
        return server, v
    except Exception as e:
        print(f"Error fetching version for {server}: {e}", file=sys.stderr)
        return server, None


async def main():
    with open("registry.toml", "rb") as f:
        wiki = tomllib.load(f)

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        tasks = [
            fetch_version(client, server, config)
            for server, config in wiki.items()
            if isinstance(config, dict)
        ]
        results = await asyncio.gather(*tasks)

    versions = {s: v for s, v in results if v is not None}
    json.dump(versions, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    asyncio.run(main())
