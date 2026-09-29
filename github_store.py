"""
Minimal GitHub Contents API client.

Lets the running app read and write small CSV files directly to this repo
at runtime, so user-submitted data (rule proposals, votes) persists across
redeploys without needing a separate database. Streamlit Cloud's local
filesystem is wiped on every redeploy - this repo, via the API, is not.

Every write creates a small commit. Fine for occasional user actions
(proposing a rule, casting a vote); not meant for high-frequency writes.
"""

import base64
import csv
import io
import time

import requests

API_BASE = "https://api.github.com"


class GitHubStoreError(Exception):
    pass


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_file(token: str, repo: str, path: str, branch: str = "main"):
    """Return (text_content, sha), or (None, None) if the file doesn't exist yet."""
    url = f"{API_BASE}/repos/{repo}/contents/{path}"
    resp = requests.get(url, headers=_headers(token), params={"ref": branch}, timeout=15)
    if resp.status_code == 404:
        return None, None
    if resp.status_code != 200:
        raise GitHubStoreError(f"GitHub API error {resp.status_code} reading {path}: {resp.text[:300]}")
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def put_file(token: str, repo: str, path: str, content: str, message: str, sha: str = None, branch: str = "main") -> str:
    """Create or update a file. Returns the new sha."""
    url = f"{API_BASE}/repos/{repo}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    resp = requests.put(url, headers=_headers(token), json=payload, timeout=15)
    if resp.status_code not in (200, 201):
        raise GitHubStoreError(f"GitHub API error {resp.status_code} writing {path}: {resp.text[:300]}")
    return resp.json()["content"]["sha"]


def put_files(token: str, repo: str, files: dict, message: str, branch: str = "main", max_retries: int = 3) -> str:
    """Write several files in ONE commit. files maps repo path -> text.

    put_file makes a commit per file, and on main every commit is a Render
    redeploy - a season update touches nine files. This builds the commit
    through the Git Data API instead. Returns the new commit's sha.
    """
    git = f"{API_BASE}/repos/{repo}/git"
    headers = _headers(token)

    def check(resp, what, ok=(200, 201)):
        if resp.status_code not in ok:
            raise GitHubStoreError(f"GitHub API error {resp.status_code} {what}: {resp.text[:300]}")
        return resp.json()

    blobs = {}
    for path, content in files.items():
        resp = requests.post(f"{git}/blobs", headers=headers, timeout=60,
                             json={"content": content, "encoding": "utf-8"})
        blobs[path] = check(resp, f"uploading {path}")["sha"]

    last_error = None
    for attempt in range(max_retries):
        try:
            head = check(requests.get(f"{git}/ref/heads/{branch}", headers=headers, timeout=15),
                         f"reading branch {branch}")["object"]["sha"]
            base_tree = check(requests.get(f"{git}/commits/{head}", headers=headers, timeout=15),
                              f"reading commit {head}")["tree"]["sha"]
            tree = check(requests.post(f"{git}/trees", headers=headers, timeout=30, json={
                "base_tree": base_tree,
                "tree": [{"path": path, "mode": "100644", "type": "blob", "sha": sha}
                         for path, sha in blobs.items()],
            }), "building tree")["sha"]
            commit = check(requests.post(f"{git}/commits", headers=headers, timeout=15, json={
                "message": message, "tree": tree, "parents": [head],
            }), "creating commit")["sha"]
            # Not forced: if the app committed a trade or bet in between,
            # this fails and the next attempt rebuilds on the new head.
            check(requests.patch(f"{git}/refs/heads/{branch}", headers=headers, timeout=15,
                                 json={"sha": commit, "force": False}), f"updating {branch}")
            return commit
        except GitHubStoreError as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise last_error


def read_csv_rows(token: str, repo: str, path: str) -> list:
    """Read a CSV file from the repo as a list of dicts. Empty list if it doesn't exist."""
    content, _ = get_file(token, repo, path)
    if not content:
        return []
    return list(csv.DictReader(io.StringIO(content)))


def append_csv_row(token: str, repo: str, path: str, fieldnames: list, row: dict, commit_message: str, max_retries: int = 3):
    """Append one row to a CSV file, creating it (with a header) if needed.

    Retries on a sha conflict, which happens if two people write at nearly
    the same instant - GitHub rejects the second write until it re-reads
    the latest sha.
    """
    last_error = None
    for attempt in range(max_retries):
        content, sha = get_file(token, repo, path)

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
        if content is None:
            writer.writeheader()
        writer.writerow(row)
        new_content = (content or "") + buf.getvalue()

        try:
            put_file(token, repo, path, new_content, commit_message, sha=sha)
            return
        except GitHubStoreError as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise last_error
