"""
2026 proposed rule changes: proposals and votes, stored via the GitHub
Contents API (see github_store.py) so they persist across redeploys without
a separate database.

Voting has no login system, so "one vote per proposal" is enforced by a
persistent anonymous browser identifier (a cookie) rather than an account -
see app.py for how that cookie is set/read. Someone who clears cookies can
vote again; that tradeoff was an explicit, accepted decision.
"""

import uuid
from datetime import datetime, timezone

import pandas as pd

import github_store

PROPOSALS_PATH = "data/rule_changes/proposals.csv"
VOTES_PATH = "data/rule_changes/votes.csv"

PROPOSAL_FIELDS = ["proposal_id", "created_at", "proposer_name", "proposal_text"]
VOTE_FIELDS = ["proposal_id", "voter_id", "voter_name", "vote", "created_at"]

VOTE_CHOICES = {"up": "✅ Up", "down": "❌ Down", "abstain": "➖ Abstain"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_proposals(token: str, repo: str) -> pd.DataFrame:
    rows = github_store.read_csv_rows(token, repo, PROPOSALS_PATH)
    df = pd.DataFrame(rows, columns=PROPOSAL_FIELDS)
    if not df.empty:
        df = df.sort_values("created_at", ascending=False).reset_index(drop=True)
    return df


def load_votes(token: str, repo: str) -> pd.DataFrame:
    rows = github_store.read_csv_rows(token, repo, VOTES_PATH)
    return pd.DataFrame(rows, columns=VOTE_FIELDS)


def vote_tally(votes: pd.DataFrame, proposal_id: str) -> dict:
    """Up/down/abstain counts for one proposal."""
    one = votes[votes["proposal_id"] == proposal_id]
    counts = one["vote"].value_counts().to_dict()
    return {choice: int(counts.get(choice, 0)) for choice in VOTE_CHOICES}


def existing_vote(votes: pd.DataFrame, proposal_id: str, voter_id: str) -> str | None:
    """The vote this browser already cast on this proposal, if any."""
    match = votes[(votes["proposal_id"] == proposal_id) & (votes["voter_id"] == voter_id)]
    if match.empty:
        return None
    return match.iloc[0]["vote"]


def add_proposal(token: str, repo: str, proposer_name: str, proposal_text: str) -> str:
    proposal_id = uuid.uuid4().hex[:8]
    row = {
        "proposal_id": proposal_id,
        "created_at": _now(),
        "proposer_name": proposer_name.strip(),
        "proposal_text": proposal_text.strip(),
    }
    github_store.append_csv_row(
        token, repo, PROPOSALS_PATH, PROPOSAL_FIELDS, row,
        commit_message=f"Add 2026 rule proposal from {proposer_name.strip()}",
    )
    return proposal_id


class AlreadyVotedError(Exception):
    pass


def add_vote(token: str, repo: str, proposal_id: str, voter_id: str, voter_name: str, vote: str):
    if vote not in VOTE_CHOICES:
        raise ValueError(f"vote must be one of {list(VOTE_CHOICES)}, got {vote!r}")

    # Re-check against the live data right before writing, not whatever was
    # loaded (possibly up to ttl=10s stale) when the page rendered - closes
    # the race where someone submits from two open tabs before either page
    # rerenders and hides the vote form.
    current_votes = load_votes(token, repo)
    if existing_vote(current_votes, proposal_id, voter_id) is not None:
        raise AlreadyVotedError("This browser has already voted on this proposal.")

    row = {
        "proposal_id": proposal_id,
        "voter_id": voter_id,
        "voter_name": voter_name.strip(),
        "vote": vote,
        "created_at": _now(),
    }
    github_store.append_csv_row(
        token, repo, VOTES_PATH, VOTE_FIELDS, row,
        commit_message=f"Add vote ({vote}) from {voter_name.strip()} on proposal {proposal_id}",
    )
