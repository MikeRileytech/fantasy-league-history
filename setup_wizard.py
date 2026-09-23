"""
First-run setup: tell the app who each ESPN account really is.

Everything else in this dashboard is derived from ESPN automatically. This
one step cannot be - only someone who was in the league knows that
"dalehiggins" was Scott Flett for six seasons, or that a team changed hands
in 2019. Historically that meant hand-editing manager_mapping.csv in a
spreadsheet, which is fine for the person who wrote the importer and a
non-starter for anyone else.

So this module puts that step in the browser: the commissioner types one
real name per ESPN account, and the mapping is written for every season
that account played.

Persistence note: Streamlit Community Cloud wipes the container filesystem
on every redeploy, so saving locally is not enough for a hosted app. When a
GitHub token and repo are configured, the mapping is also committed back to
the repo - the same trick the rule-changes tab uses for votes - which both
survives redeploys and leaves an auditable history of who was named what.
"""

import os

import pandas as pd
import streamlit as st

import github_store
import league_data

MAPPING_PATH = "manager_mapping.csv"


def github_config():
    """(token, repo), either of which may be None when not configured.

    Read from the environment locally and from Streamlit secrets when hosted.

    There is deliberately no default repo. Every deployment of this app is a
    different league, and a repo that defaulted to someone else's would mean
    one missing secret silently commits this league's names into that
    league's history. Better to save locally and say so.
    """

    def _get(name):
        value = os.getenv(name)
        if value:
            return value
        try:
            return st.secrets.get(name)
        except FileNotFoundError:
            return None

    return _get("GITHUB_TOKEN"), _get("GITHUB_REPO")


def _persist(csv_text: str) -> str | None:
    """Commit the mapping to GitHub. Returns an error string, or None on success.

    Not reaching GitHub is not fatal - the local write already happened, so
    the app is correct for this session either way. The caller surfaces the
    message so a self-hosted user is not nagged about a feature they never
    configured.
    """
    token, repo = github_config()
    if not token and not repo:
        # Nothing configured: a local or self-hosted run, where the file
        # write is the whole story. Nothing to report.
        return None
    if not token or not repo:
        missing = "GITHUB_REPO" if token else "GITHUB_TOKEN"
        return (
            f"{missing} is not set, so this was only saved to the running "
            "app and will be lost the next time it redeploys."
        )
    try:
        _, sha = github_store.get_file(token, repo, MAPPING_PATH)
        github_store.put_file(
            token,
            repo,
            MAPPING_PATH,
            csv_text,
            "Update manager names from in-app setup",
            sha=sha,
        )
    except github_store.GitHubStoreError as exc:
        return str(exc)
    return None


def _save(mapping: pd.DataFrame) -> None:
    """Write the mapping everywhere it needs to go, then rerun."""
    csv_text = league_data.save_mapping(mapping)
    error = _persist(csv_text)
    if error:
        st.session_state["_setup_warning"] = (
            "Saved for this session, but could not write to GitHub, so the "
            f"change will be lost on the next redeploy: {error}"
        )
    else:
        st.session_state["_setup_notice"] = "Manager names saved."
    st.rerun()


def _account_editor(mapping: pd.DataFrame, key: str) -> None:
    """One row per ESPN account: type the real name next to each."""
    accounts = league_data.espn_accounts(mapping)

    split = accounts[accounts["split"]]
    if len(split):
        st.info(
            "These ESPN accounts already have different names in different "
            "seasons, so they were left blank rather than guessed: "
            + ", ".join(split["espn_account"])
            + ". Fill them in below to use one name for every season, or "
            "leave them and use the per-season table."
        )

    edited = st.data_editor(
        accounts[["espn_account", "manager", "seasons", "teams"]],
        hide_index=True,
        use_container_width=True,
        disabled=["espn_account", "seasons", "teams"],
        column_config={
            "espn_account": st.column_config.TextColumn(
                "ESPN account", help="The username ESPN has on file."
            ),
            "manager": st.column_config.TextColumn(
                "Real name",
                help="Who actually played these seasons. Spelling matters - "
                "use the same name everywhere for the same person.",
                required=False,
            ),
            "seasons": st.column_config.TextColumn("Seasons"),
            "teams": st.column_config.TextColumn("Team names used"),
        },
        key=key,
    )

    unnamed = [
        row.espn_account
        for row in edited.itertuples()
        if not str(row.manager).strip()
    ]
    if unnamed:
        st.caption(
            f"{len(unnamed)} account(s) still unnamed - they will keep their "
            "ESPN username."
        )

    if st.button("Save names", type="primary", key=f"{key}_save"):
        names = {
            row.espn_account: row.manager
            for row in edited.itertuples()
            if str(row.manager).strip()
        }
        if not names:
            st.warning("Type at least one name first.")
        else:
            _save(league_data.apply_account_names(mapping, names))


def _season_editor(mapping: pd.DataFrame, key: str) -> None:
    """The escape hatch: edit one team-season at a time.

    Needed when an ESPN account was handed to a different person partway
    through the league's history, which the account-level screen cannot
    express by construction.
    """
    st.caption(
        "Use this when a single ESPN account was used by different people in "
        "different years. Edits here are kept even if you save the account "
        "table again."
    )
    edited = st.data_editor(
        mapping[["season", "espn_team_id", "team_name", "owner_names", "manager"]],
        hide_index=True,
        use_container_width=True,
        disabled=["season", "espn_team_id", "team_name", "owner_names"],
        column_config={
            "season": st.column_config.NumberColumn("Season", format="%d"),
            "espn_team_id": st.column_config.NumberColumn("Team ID", format="%d"),
            "team_name": st.column_config.TextColumn("Team name"),
            "owner_names": st.column_config.TextColumn("ESPN account"),
            "manager": st.column_config.TextColumn("Real name"),
        },
        key=key,
    )
    if st.button("Save per-season names", key=f"{key}_save"):
        updated = mapping.copy()
        updated["manager"] = edited["manager"].values
        _save(updated)


def _flush_messages() -> None:
    notice = st.session_state.pop("_setup_notice", None)
    warning = st.session_state.pop("_setup_warning", None)
    if notice:
        st.success(notice)
    if warning:
        st.warning(warning)


def render_gate(mapping: pd.DataFrame) -> None:
    """Full-page setup shown when the league has never been named.

    The caller stops the app after this, because every screen behind it
    would otherwise be labelled with ESPN usernames.
    """
    st.title("Set up your league")
    _flush_messages()
    st.write(
        f"Your league's history imported cleanly - **{mapping['season'].nunique()} "
        f"seasons**, **{len(mapping)}** team-seasons. One step left."
    )
    st.write(
        "ESPN records history against *team slots*, not people, so a team that "
        "changed hands still shows the original owner. Tell us who each ESPN "
        "account really is and every record in this app will follow the real "
        "person instead."
    )
    st.divider()
    _account_editor(mapping, key="setup_gate_accounts")
    with st.expander("A team changed hands partway through our history"):
        _season_editor(mapping, key="setup_gate_seasons")


def render_editor(mapping: pd.DataFrame) -> None:
    """The same editor, reachable from inside the app for later corrections."""
    st.subheader("Manager names")
    st.caption(
        "Who each ESPN account really is. Changing a name here updates every "
        "record in the app - standings, head-to-head, draft history."
    )
    _flush_messages()
    _account_editor(mapping, key="settings_accounts")
    with st.expander("Per-season names (for teams that changed hands)"):
        _season_editor(mapping, key="settings_seasons")
