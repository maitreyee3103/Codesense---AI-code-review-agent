import os
import re
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

GITHUB_API = "https://api.github.com"
TOKEN = os.getenv("GITHUB_TOKEN")


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Return (owner, repo, pr_number) from a GitHub PR URL."""
    match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url.rstrip("/")
    )
    if not match:
        raise ValueError(f"Not a valid GitHub PR URL: {url}")
    owner, repo, number = match.groups()
    return owner, repo, int(number)


def fetch_pr(url: str) -> dict:
    """Fetch PR metadata + file diffs. Returns a unified dict."""
    owner, repo, number = parse_pr_url(url)

    # PR metadata
    meta_resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}",
        headers=_headers(),
        timeout=30,
    )
    meta_resp.raise_for_status()
    meta = meta_resp.json()

    # Changed files with patches
    files_resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/files",
        headers=_headers(),
        params={"per_page": 100},
        timeout=30,
    )
    files_resp.raise_for_status()
    files = files_resp.json()

    changed_files = [
        {
            "filename": f["filename"],
            "status": f["status"],          # added / modified / removed / renamed
            "additions": f["additions"],
            "deletions": f["deletions"],
            "patch": f.get("patch", ""),    # unified diff — absent for binary files
        }
        for f in files
    ]

    return {
        "url": url,
        "owner": owner,
        "repo": repo,
        "number": number,
        "title": meta["title"],
        "description": meta.get("body") or "",
        "author": meta["user"]["login"],
        "base_branch": meta["base"]["ref"],
        "head_branch": meta["head"]["ref"],
        "state": meta["state"],
        "changed_files": changed_files,
    }
