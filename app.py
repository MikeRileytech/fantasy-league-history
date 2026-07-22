"""
League history dashboard.

Run it with:
    streamlit run app.py
"""

import importlib
import json
import os
import uuid

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

import league_data

# Streamlit hot-reloads app.py on redeploy but keeps imported modules cached
# in the running process, which has repeatedly left league_data stale (both
# locally and on Streamlit Cloud). Reloading is cheap - the module is only
# function definitions - and guarantees app.py and league_data.py match.
league_data = importlib.reload(league_data)

load_dotenv()

st.set_page_config(page_title="League History", page_icon="🏈", layout="wide")

@st.cache_data(show_spinner="Loading league data...")
def load_all(cache_key):
    """Load all league data.

    cache_key is a fingerprint of the data files (paths + modification
    times), so editing manager_mapping.csv or reimporting a season
    automatically busts the cache. NOTE: the parameter must NOT start
    with an underscore - Streamlit excludes underscore-prefixed
    parameters from the cache key.
    """
    teams = league_data.load_teams()
    matchups = league_data.load_matchups()
    draft = league_data.load_draft()
    return teams, matchups, draft


try:
    teams, matchups, draft = load_all(cache_key=league_data.data_fingerprint())
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

st.title("🏈 Fantasy League History")
seasons = sorted(teams["season"].unique())
st.caption(f"{seasons[0]}–{seasons[-1]} · {teams['manager'].nunique()} managers")

tab_alltime, tab_trophies, tab_seasons, tab_h2h, tab_tx, tab_draft, tab_charts, tab_rules, tab_ask = st.tabs(
    ["All-Time Standings", "Trophies", "Season Browser", "Head-to-Head", "Transactions", "Draft History", "Charts", "2026 Proposed Rule Changes", "Ask the League"]
)

with tab_alltime:
    st.subheader("Career records by manager")
    st.caption(
        "Grouped by real manager (not ESPN team), using manager_mapping.csv. "
        "Sorted by championships, then win percentage."
    )
    col1, col2 = st.columns(2)
    with col1:
        view_mode = st.radio(
            "View",
            ["Regular + Playoff", "Playoff Games Only", "Regular Games Only"],
            horizontal=True,
            key="career_view_mode"
        )
    with col2:
        at_consolation = st.checkbox("Include consolation games", value=False, key="at_cons")

    # Set game types based on selected view
    if view_mode == "Regular + Playoff":
        at_game_types = ["regular", "playoff"]
    elif view_mode == "Playoff Games Only":
        at_game_types = ["playoff"]
    else:  # Regular Games Only
        at_game_types = ["regular"]

    if at_consolation:
        at_game_types.append("consolation")

    career = league_data.manager_career_standings(teams, matchups, game_types=at_game_types)
    logos = league_data.manager_logos(teams)
    career.insert(0, "logo", career["manager"].map(logos))

    extra_col_labels = {
        "Seasons": "seasons",
        "First season": "first_season",
        "Last season": "last_season",
        "Points For (PF)": "points_for",
        "Points Against (PA)": "points_against",
    }
    extra_picked = st.multiselect(
        "➕ Show additional stats",
        options=list(extra_col_labels.keys()),
        default=[],
        key="career_extra_cols",
    )
    extra_cols = [extra_col_labels[label] for label in extra_picked]

    st.dataframe(
        career,
        width='stretch',
        hide_index=True,
        column_order=["logo", "manager", "championships", "wins", "losses", "ties", "win_pct"]
        + extra_cols,
        column_config={
            "logo": st.column_config.ImageColumn(" "),
            "manager": "Manager",
            "seasons": "Seasons",
            "first_season": st.column_config.NumberColumn("First", format="%d"),
            "last_season": st.column_config.NumberColumn("Last", format="%d"),
            "wins": "W",
            "losses": "L",
            "ties": "T",
            "win_pct": st.column_config.NumberColumn("Win %", format="%.3f"),
            "points_for": st.column_config.NumberColumn("PF", format="%.1f"),
            "points_against": st.column_config.NumberColumn("PA", format="%.1f"),
            "championships": "🏆",
        },
    )

with tab_trophies:
    st.subheader("Trophy case")
    st.caption(
        "Career trophy counts per manager. Championships are the overall "
        "playoff title - the most prestigious award."
    )
    trophies = league_data.season_trophies(teams, matchups)
    weekly_winners = league_data.weekly_high_winners(matchups)
    case = league_data.trophy_case(trophies, weekly_winners)
    case.insert(0, "logo", case["manager"].map(logos))
    st.dataframe(
        case,
        width='stretch',
        hide_index=True,
        column_config={
            "logo": st.column_config.ImageColumn(" "),
            "manager": "Manager",
            "championships": "🏆 Championships",
            "regular_season_titles": "🎖️ Reg. Season Titles",
            "points_titles": "🔥 Points Titles",
            "weekly_highs": "⚡ Weekly Highs",
            "total": "Total",
        },
    )

    st.divider()
    st.subheader("Season by season")
    st.caption(
        "🏆 Champion: won the playoff bracket. 🎖️ Regular Season Winner: best "
        "regular season record. 🔥 Points Leader: most total points in the "
        "regular season. ⚡ Best Week: biggest single-week score of the season."
    )
    st.dataframe(
        trophies.sort_values("season", ascending=False),
        width='stretch',
        hide_index=True,
        column_config={
            "season": st.column_config.NumberColumn("Season", format="%d"),
            "champion": "🏆 Champion",
            "regular_season_winner": "🎖️ Reg. Season Winner",
            "regular_season_record": "Record",
            "points_leader": "🔥 Points Leader",
            "points": st.column_config.NumberColumn("Points", format="%.1f"),
            "best_week": "⚡ Best Week",
            "best_week_score": st.column_config.NumberColumn("Score", format="%.1f"),
            "best_week_number": st.column_config.NumberColumn("Week", format="%d"),
        },
    )

    st.divider()
    st.subheader("⚡ Weekly high scores")
    st.caption(
        "Every regular season week hands out one weekly points award. "
        "13 weeks per season through 2020, 14 since the NFL added an 18th week."
    )
    weekly_season = st.selectbox(
        "Season", sorted(weekly_winners["season"].unique(), reverse=True),
        key="weekly_high_season",
    )
    st.dataframe(
        weekly_winners[weekly_winners["season"] == weekly_season][
            ["week", "manager", "score"]
        ],
        width='stretch',
        hide_index=True,
        column_config={
            "week": st.column_config.NumberColumn("Week", format="%d"),
            "manager": "⚡ Weekly High",
            "score": st.column_config.NumberColumn("Score", format="%.1f"),
        },
    )

with tab_seasons:
    col_season, col_browser_manager = st.columns(2)
    with col_season:
        season = st.selectbox("Season", seasons, index=len(seasons) - 1, key="browser_season")
    with col_browser_manager:
        browser_manager = st.selectbox(
            "Manager",
            ["All"] + sorted(teams["manager"].dropna().unique().tolist()),
            index=0,
            key="browser_manager",
        )

    if browser_manager == "All":
        st.subheader(f"{season} final standings")
        standings = league_data.season_standings(teams, season)
        champ = standings.iloc[0]
        st.success(f"🏆 Champion: **{champ['manager']}** ({champ['team_name']})")
        st.dataframe(
            standings,
            width='stretch',
            height="content",
            hide_index=True,
            column_config={
                "final_standing": "Final",
                "regular_season_standing": "Reg. Season",
                "logo_url": st.column_config.ImageColumn(" "),
                "team_name": "Team",
                "manager": "Manager",
                "wins": "W",
                "losses": "L",
                "ties": "T",
                "points_for": st.column_config.NumberColumn("PF", format="%.1f"),
                "points_against": st.column_config.NumberColumn("PA", format="%.1f"),
            },
        )
    else:
        history = league_data.manager_season_history(teams, browser_manager)
        championships = int((history["final_standing"] == 1).sum())
        st.subheader(f"{browser_manager}'s season-by-season history")
        st.caption(f"{len(history)} seasons played · {championships} championship(s)")
        st.dataframe(
            history,
            width='stretch',
            height="content",
            hide_index=True,
            column_config={
                "season": st.column_config.NumberColumn("Season", format="%d"),
                "final_standing": "Final",
                "regular_season_standing": "Reg. Season",
                "logo_url": st.column_config.ImageColumn(" "),
                "team_name": "Team",
                "wins": "W",
                "losses": "L",
                "ties": "T",
                "points_for": st.column_config.NumberColumn("PF", format="%.1f"),
                "points_against": st.column_config.NumberColumn("PA", format="%.1f"),
            },
        )

with tab_h2h:
    st.subheader("Head-to-head records")
    st.caption("Read across a row: that manager's record against each opponent.")
    col_view, col_cons = st.columns(2)
    with col_view:
        h2h_view = st.radio(
            "View",
            ["Regular + Playoff", "Playoff Games Only", "Regular Games Only"],
            horizontal=True,
            key="h2h_view_mode",
        )
    with col_cons:
        with_consolation = st.checkbox("Include consolation games", value=False)

    if h2h_view == "Regular + Playoff":
        game_types = ["regular", "playoff"]
    elif h2h_view == "Playoff Games Only":
        game_types = ["playoff"]
    else:  # Regular Games Only
        game_types = ["regular"]

    if with_consolation:
        game_types.append("consolation")
    grid = league_data.head_to_head(matchups, game_types=game_types)
    st.dataframe(grid, width='stretch')

with tab_tx:
    st.subheader("Transactions")
    st.caption(
        "Trades, waiver claims, and roster moves. ESPN only retains "
        "transaction logs from 2018 onward, and its player detail on some "
        "older trades is incomplete."
    )

    @st.cache_data(show_spinner=False)
    def load_transactions_cached(cache_key):
        return league_data.load_transactions()

    try:
        transactions = load_transactions_cached(league_data.data_fingerprint())
    except FileNotFoundError:
        st.info("No transaction data imported yet. Run espn_transactions_importer.py --all first.")
        transactions = None

    if transactions is not None:
        st.markdown("### 💰 Biggest FAAB bids of all time")
        bids = league_data.faab_bids(transactions)
        st.dataframe(
            bids.head(20).drop(columns=["date"]),
            width='stretch',
            hide_index=True,
            column_config={
                "season": st.column_config.NumberColumn("Season", format="%d"),
                "week": st.column_config.NumberColumn("Week", format="%d"),
                "manager": "Manager",
                "player_name": "Player",
                "bid_amount": st.column_config.NumberColumn("Bid", format="$%d"),
            },
        )

        st.divider()
        st.markdown("### ⚔️ Waiver bid history & bidding wars")
        st.caption(
            "Every bid ever placed, including the losers. Bids on the same "
            "player in the same week sit together (highest first), so each "
            "bidding war reads top to bottom. 'Contested only' keeps just "
            "the players multiple managers fought over. For the season "
            "currently being played, only winning bids are shown (ESPN makes "
            "those public already) - losing bids stay hidden until the "
            "season ends, since a manager never sees what others bid and lost."
        )
        bids_all = league_data.waiver_bids(transactions)
        col_bw1, col_bw2, col_bw3 = st.columns(3)
        with col_bw1:
            bw_season = st.selectbox(
                "Season",
                ["All"] + sorted(bids_all["season"].unique().tolist(), reverse=True),
                key="bw_season",
            )
        with col_bw2:
            bw_manager = st.selectbox(
                "Manager",
                ["All"] + sorted(bids_all["manager"].dropna().unique().tolist()),
                key="bw_manager",
            )
        with col_bw3:
            bw_outcomes = st.multiselect(
                "Outcomes",
                sorted(bids_all["outcome"].unique().tolist()),
                default=["Won", "Lost"],
                key="bw_outcomes",
            )
        col_bw4, col_bw5 = st.columns(2)
        with col_bw4:
            bw_player = st.text_input("Player search", key="bw_player")
        with col_bw5:
            bw_contested = st.checkbox(
                "Contested only (2+ bids on the player that week)", key="bw_contested"
            )

        shown_bids = bids_all
        if bw_season != "All":
            shown_bids = shown_bids[shown_bids["season"] == bw_season]
        if bw_outcomes:
            shown_bids = shown_bids[shown_bids["outcome"].isin(bw_outcomes)]
        if bw_contested:
            counts = shown_bids.groupby(["season", "week", "player_name"])[
                "manager"
            ].transform("nunique")
            shown_bids = shown_bids[counts > 1]
        # Manager and player filters come last so a bidding war stays intact
        # while 'contested' is judged against all managers' bids.
        if bw_manager != "All":
            shown_bids = shown_bids[shown_bids["manager"] == bw_manager]
        if bw_player:
            shown_bids = shown_bids[
                shown_bids["player_name"].str.contains(bw_player, case=False, na=False)
            ]

        st.caption(f"{len(shown_bids)} bids shown")
        st.dataframe(
            shown_bids.drop(columns=["date"]),
            width='stretch',
            hide_index=True,
            height=420,
            column_config={
                "season": st.column_config.NumberColumn("Season", format="%d"),
                "week": st.column_config.NumberColumn("Week", format="%d"),
                "manager": "Manager",
                "player_name": "Player",
                "bid_amount": st.column_config.NumberColumn("Bid", format="$%d"),
                "outcome": "Outcome",
            },
        )

        st.divider()
        st.markdown("### 📋 Transaction log")
        st.caption(
            "Every executed roster move since 2018. Click any column header "
            "to sort; combine the filters to answer questions like 'every "
            "FAAB claim George made in 2022'."
        )
        log = league_data.transaction_log(transactions)
        col_season, col_mgr, col_action = st.columns(3)
        with col_season:
            log_season = st.selectbox(
                "Season",
                ["All"] + sorted(log["season"].unique().tolist(), reverse=True),
                key="log_season",
            )
        with col_mgr:
            log_manager = st.selectbox(
                "Manager",
                ["All"] + sorted(log["manager"].dropna().unique().tolist()),
                key="log_manager",
            )
        with col_action:
            log_actions = st.multiselect(
                "Move types",
                ["Waiver claim", "Free agent pickup", "Drop"],
                default=["Waiver claim", "Free agent pickup", "Drop"],
                key="log_actions",
            )

        shown_log = log
        if log_season != "All":
            shown_log = shown_log[shown_log["season"] == log_season]
        if log_manager != "All":
            shown_log = shown_log[shown_log["manager"] == log_manager]
        if log_actions:
            shown_log = shown_log[shown_log["action"].isin(log_actions)]

        faab_shown = int(shown_log.loc[shown_log["action"] == "Waiver claim", "bid_amount"].sum())
        st.caption(f"{len(shown_log)} moves shown · ${faab_shown} FAAB spent in this view")
        st.dataframe(
            shown_log.drop(columns=["date"]),
            width='stretch',
            hide_index=True,
            height=420,
            column_config={
                "season": st.column_config.NumberColumn("Season", format="%d"),
                "week": st.column_config.NumberColumn("Week", format="%d"),
                "manager": "Manager",
                "action": "Action",
                "player_name": "Player",
                "bid_amount": st.column_config.NumberColumn("FAAB", format="$%d"),
            },
        )

        st.divider()
        st.markdown("### 🔄 Roster activity by manager (2018+)")
        st.caption("Who actually works the wire - total adds, drops, and FAAB spent.")
        activity = league_data.transaction_activity(transactions)
        st.dataframe(
            activity,
            width='stretch',
            hide_index=True,
            column_config={
                "manager": "Manager",
                "adds": "Adds",
                "drops": "Drops",
                "waiver_claims": "Waiver Claims",
                "faab_spent": st.column_config.NumberColumn("FAAB Spent", format="$%d"),
            },
        )

with tab_draft:
    st.subheader("Draft history")
    st.caption(
        "Filter by season, round, and manager to answer questions like "
        "'every first-round pick I've ever made' - pick 'All' seasons and "
        "round 1, then your manager."
    )
    table = league_data.draft_table(draft)
    col1, col2, col3 = st.columns(3)
    with col1:
        draft_season = st.selectbox(
            "Season", ["All"] + seasons, index=0, key="draft_season"
        )
    with col2:
        draft_round = st.selectbox(
            "Round",
            ["All"] + sorted(table["round"].unique().tolist()),
            index=0,
            key="draft_round",
        )
    with col3:
        draft_manager = st.selectbox(
            "Filter Manager",
            ["All"] + sorted(table["manager"].dropna().unique().tolist()),
            index=0,
            key="draft_manager",
        )
    player_search = st.text_input("Search player", key="draft_player_search")

    if draft_season != "All":
        table = table[table["season"] == draft_season]
    if draft_round != "All":
        table = table[table["round"] == draft_round]
    if draft_manager != "All":
        table = table[table["manager"] == draft_manager]
    if player_search:
        table = table[
            table["player_name"].str.contains(player_search, case=False, na=False)
        ]
    st.dataframe(
        table,
        width='stretch',
        hide_index=True,
        column_config={
            "season": st.column_config.NumberColumn("Season", format="%d"),
            "round": "Rd",
            "pick_in_round": "Pick",
            "overall_pick": "Overall",
            "player_name": "Player",
            "position": "Pos",
            "manager": "Manager",
            "team_name": "Team",
            "is_keeper": "Keeper",
        },
    )

with tab_charts:
    import altair as alt

    # Colorblind-validated categorical palette; each manager keeps a fixed
    # color regardless of which managers are selected.
    PALETTE = ["#2a78d6", "#1baf7a", "#eda100", "#008300",
               "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]

    st.subheader("Career win percentage")
    st.caption("Regular season + playoff games (consolation excluded).")
    career = league_data.manager_career_standings(teams, matchups)
    career_active = career[career["wins"] + career["losses"] + career["ties"] > 0]

    # Fixed color per manager, assigned in career-table order so the managers
    # people actually chart (top of the table, the default selection) always
    # get distinct colors.
    all_managers = career_active["manager"].tolist() + sorted(
        set(teams["manager"].dropna()) - set(career_active["manager"])
    )
    manager_colors = {m: PALETTE[i % len(PALETTE)] for i, m in enumerate(all_managers)}
    winpct_chart = (
        alt.Chart(career_active)
        .mark_bar(color="#2a78d6", cornerRadiusEnd=4, height={"band": 0.6})
        .encode(
            x=alt.X("win_pct:Q", title="Career win %", axis=alt.Axis(format=".0%")),
            y=alt.Y("manager:N", sort="-x", title=None),
            tooltip=[
                alt.Tooltip("manager:N", title="Manager"),
                alt.Tooltip("wins:Q", title="Wins"),
                alt.Tooltip("losses:Q", title="Losses"),
                alt.Tooltip("win_pct:Q", title="Win %", format=".3f"),
                alt.Tooltip("championships:Q", title="Championships"),
            ],
        )
        .properties(height=480)
    )
    st.altair_chart(winpct_chart, width='stretch')

    st.divider()
    st.subheader("Manager history over time")
    default_managers = career_active.head(6)["manager"].tolist()
    picked = st.multiselect(
        "Managers to show (up to 8)",
        all_managers,
        default=default_managers,
        max_selections=8,
    )

    if picked:
        color_scale = alt.Scale(
            domain=picked, range=[manager_colors[m] for m in picked]
        )
        seasons_axis = alt.X(
            "season:O", title="Season", axis=alt.Axis(labelAngle=0)
        )

        st.markdown("**Final standing by season** (1 = champion)")
        finish = teams[teams["manager"].isin(picked)]
        finish_chart = (
            alt.Chart(finish)
            .mark_line(point=alt.OverlayMarkDef(size=70), strokeWidth=2)
            .encode(
                x=seasons_axis,
                y=alt.Y(
                    "final_standing:Q",
                    title="Final standing",
                    scale=alt.Scale(reverse=True, domainMin=1),
                    axis=alt.Axis(tickMinStep=1),
                ),
                color=alt.Color("manager:N", scale=color_scale, title="Manager"),
                tooltip=[
                    alt.Tooltip("manager:N", title="Manager"),
                    alt.Tooltip("season:O", title="Season"),
                    alt.Tooltip("final_standing:Q", title="Finished"),
                    alt.Tooltip("team_name:N", title="Team"),
                ],
            )
            .properties(height=340)
        )
        st.altair_chart(finish_chart, width='stretch')

        st.markdown("**Cumulative career wins** (regular season + playoffs)")
        cumwins = league_data.cumulative_wins(matchups)
        cumwins = cumwins[cumwins["manager"].isin(picked)]
        cumwins_chart = (
            alt.Chart(cumwins)
            .mark_line(point=alt.OverlayMarkDef(size=70), strokeWidth=2)
            .encode(
                x=seasons_axis,
                y=alt.Y("cumulative_wins:Q", title="Career wins"),
                color=alt.Color("manager:N", scale=color_scale, title="Manager"),
                tooltip=[
                    alt.Tooltip("manager:N", title="Manager"),
                    alt.Tooltip("season:O", title="Season"),
                    alt.Tooltip("cumulative_wins:Q", title="Career wins"),
                ],
            )
            .properties(height=340)
        )
        st.altair_chart(cumwins_chart, width='stretch')
    else:
        st.info("Pick at least one manager to see the history charts.")

with tab_rules:
    st.subheader("2026 Proposed Rule Changes")
    st.caption(
        "Propose a rule change for next season, or vote on existing "
        "proposals. Proposing and voting both require a name. Voting is "
        "limited to once per proposal per browser - it's tracked with a "
        "cookie, not a login, so it isn't foolproof, but it's the best "
        "option without making everyone create an account."
    )

    import rule_changes

    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        try:
            github_token = st.secrets.get("GITHUB_TOKEN")
        except FileNotFoundError:
            github_token = None
    GITHUB_REPO = "MikeRileytech/fantasy-league-history"

    if not github_token:
        st.warning(
            "No GITHUB_TOKEN found. Locally: add it to your .env file. On "
            "Streamlit Community Cloud: add it under the app's Settings > "
            "Secrets. See README.md for how to create one."
        )
        st.stop()

    # A persistent anonymous voter id, stored in a first-party cookie so a
    # browser is recognized on return visits without any login. st.context
    # can only READ cookies the browser already sent; a brand-new visitor
    # has none yet, so we hand them a session-only id for this run and set
    # the cookie via injected JS - it takes effect starting next run.
    _voter_cookie = st.context.cookies.get("league_voter_id")
    if _voter_cookie:
        voter_id = _voter_cookie
    else:
        if "_voter_id_fallback" not in st.session_state:
            st.session_state["_voter_id_fallback"] = str(uuid.uuid4())
        voter_id = st.session_state["_voter_id_fallback"]
        # components.html renders in an isolated srcdoc iframe with its own
        # cookie jar - document.cookie here would set a cookie nobody else
        # can see. window.parent.document is the actual top-level page.
        components.html(
            f"""<script>
            window.parent.document.cookie = "league_voter_id={voter_id}; max-age=157680000; path=/; SameSite=Lax";
            </script>""",
            height=0,
        )

    @st.cache_data(ttl=10)
    def load_rule_data(_token, repo):
        proposals = rule_changes.load_proposals(_token, repo)
        votes = rule_changes.load_votes(_token, repo)
        return proposals, votes

    proposals, votes = load_rule_data(github_token, GITHUB_REPO)

    st.markdown("### Propose a new rule")
    with st.form("propose_rule_form", clear_on_submit=True):
        proposer_name = st.text_input("Your name (required)")
        proposal_text = st.text_area("Proposed rule change (required)")
        submitted = st.form_submit_button("Submit proposal")
        if submitted:
            if not proposer_name.strip() or not proposal_text.strip():
                st.error("Both your name and the proposal text are required.")
            else:
                with st.spinner("Saving proposal..."):
                    rule_changes.add_proposal(github_token, GITHUB_REPO, proposer_name, proposal_text)
                st.cache_data.clear()
                st.success("Proposal submitted!")
                st.rerun()

    st.divider()
    st.markdown("### Proposals")
    if proposals.empty:
        st.info("No proposals yet - be the first to submit one above.")
    else:
        for _, proposal in proposals.iterrows():
            proposal_id = proposal["proposal_id"]
            tally = rule_changes.vote_tally(votes, proposal_id)
            my_vote = rule_changes.existing_vote(votes, proposal_id, voter_id)

            with st.container(border=True):
                st.markdown(f"**{proposal['proposer_name']}** proposes:")
                st.markdown(proposal["proposal_text"])
                st.caption(
                    f"✅ {tally['up']} · ❌ {tally['down']} · ➖ {tally['abstain']}"
                )

                if my_vote:
                    st.info(f"You voted: {rule_changes.VOTE_CHOICES[my_vote]}")
                else:
                    with st.form(f"vote_form_{proposal_id}", clear_on_submit=True):
                        voter_name = st.text_input("Your name (required)", key=f"voter_name_{proposal_id}")
                        vote_choice = st.radio(
                            "Your vote",
                            list(rule_changes.VOTE_CHOICES),
                            format_func=lambda v: rule_changes.VOTE_CHOICES[v],
                            horizontal=True,
                            key=f"vote_choice_{proposal_id}",
                        )
                        vote_submitted = st.form_submit_button("Cast vote")
                        if vote_submitted:
                            if not voter_name.strip():
                                st.error("Your name is required to vote.")
                            else:
                                try:
                                    with st.spinner("Saving vote..."):
                                        rule_changes.add_vote(
                                            github_token, GITHUB_REPO, proposal_id,
                                            voter_id, voter_name, vote_choice,
                                        )
                                    st.cache_data.clear()
                                    st.rerun()
                                except rule_changes.AlreadyVotedError:
                                    st.cache_data.clear()
                                    st.warning("You've already voted on this proposal.")
                                    st.rerun()

with tab_ask:
    st.subheader("Ask the League")
    st.caption(
        "Ask anything about league history — records, streaks, draft picks, "
        "head-to-head trivia. Answers come from the imported data only."
    )

    # Local runs read the key from .env; the hosted app reads it from
    # Streamlit Community Cloud's Secrets settings.
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets.get("ANTHROPIC_API_KEY")
        except FileNotFoundError:
            api_key = None
    if not api_key:
        st.warning(
            "No ANTHROPIC_API_KEY found. Locally: add it to your .env file "
            "(see README.md, 'Setting up Ask the League'). On Streamlit "
            "Community Cloud: add it under the app's Settings > Secrets."
        )
        st.stop()

    import anthropic

    @st.cache_data
    def get_ask_context(cache_key):
        """cache_key busts the cache when data files change - see load_all()."""
        return league_data.build_ask_context(teams, matchups, draft)

    @st.cache_resource
    def get_client():
        return anthropic.Anthropic(api_key=api_key)

    QUERY_TOOL = {
        "name": "query_league_data",
        "description": (
            "Run an exact filtered/grouped query against the league's "
            "structured data. ALWAYS use this for any question that requires "
            "counting, filtering, or aggregating rows (e.g. 'how many RBs has "
            "X drafted in round 1', 'how many times has Y beaten Z', 'who has "
            "the most 1st place finishes') instead of counting by reading the "
            "LEAGUE DATA text - manually tallying thousands of rows is "
            "unreliable and must be avoided for anything countable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset": {
                    "type": "string",
                    "enum": ["draft_picks", "games", "standings"],
                    "description": (
                        "draft_picks: one row per draft pick (season, round, "
                        "pick_in_round, overall_pick, player_name, position, "
                        "manager, team_name, is_keeper). "
                        "games: one row per game (season, week, "
                        "game_type_code [R=regular/P=playoff/C=consolation], "
                        "winner, winner_pts, loser, loser_pts, outcome). "
                        "standings: one row per team-season (season, manager, "
                        "team_name, final_standing, regular_season_standing, "
                        "wins, losses, ties, points_for, points_against)."
                    ),
                },
                "filters": {
                    "type": "object",
                    "description": (
                        "Column filters for the chosen dataset. A filter "
                        "value can be: a single value for exact match, e.g. "
                        "{\"manager\": \"Kyle Schwartz\"}; a list to match any "
                        "of several values, e.g. {\"position\": [\"RB\", "
                        "\"WR\"]}; or an operator object for numeric ranges - "
                        "{\"$gte\": x}, {\"$lte\": x}, {\"$gt\": x}, "
                        "{\"$lt\": x}, {\"$in\": [...]} - combine multiple "
                        "operators in one object, e.g. {\"season\": {\"$gte\": "
                        "2020, \"$lte\": 2025}} for a season range in a single "
                        "call. Only use column names listed for that dataset "
                        "above."
                    ),
                },
                "group_by": {
                    "type": "string",
                    "description": (
                        "Optional column to aggregate matching rows per "
                        "group, e.g. 'manager'. Combine with agg_column + "
                        "agg_func for sums/averages (e.g. average points_for "
                        "per manager); omit both to just count rows per "
                        "group instead. Omit group_by entirely to get the "
                        "actual matching rows."
                    ),
                },
                "agg_column": {
                    "type": "string",
                    "description": (
                        "Numeric column to aggregate per group (requires "
                        "group_by), e.g. 'points_for'. Use this instead of "
                        "averaging/summing numbers yourself from listed rows - "
                        "manual arithmetic over many rows is unreliable, this "
                        "computes the exact value."
                    ),
                },
                "agg_func": {
                    "type": "string",
                    "enum": ["mean", "sum", "min", "max", "count"],
                    "description": "How to aggregate agg_column per group. Defaults to 'mean'.",
                },
            },
            "required": ["dataset"],
        },
    }

    def run_query_tool(tool_input):
        return league_data.query_dataset(
            teams,
            matchups,
            draft,
            dataset=tool_input.get("dataset"),
            filters=tool_input.get("filters"),
            group_by=tool_input.get("group_by"),
            agg_column=tool_input.get("agg_column"),
            agg_func=tool_input.get("agg_func"),
        )

    SYSTEM_PROMPT = [
        {
            "type": "text",
            "text": (
                "You are the historian for a fantasy football league. Answer "
                "questions using ONLY the league data below and the "
                "query_league_data tool. If neither contains the answer, say so "
                "- never guess or invent results. "
                "For ANY question that requires counting, filtering, summing, "
                "or averaging rows - how many, who has the most, average points "
                "over some seasons, every pick/game matching some condition - "
                "you MUST call query_league_data and report its exact result. "
                "Do not manually count, sum, or average numbers yourself from "
                "the LEAGUE DATA text or from rows the tool returns; with "
                "thousands of rows that is unreliable and has produced wrong, "
                "misattributed counts before - use group_by with agg_column/"
                "agg_func for any sum or average instead of doing the math "
                "yourself. The LEAGUE DATA text is for context, spot lookups, "
                "and narrative questions only. Never rely on your own "
                "knowledge of which position a player plays - query the data "
                "or read it from the text; a position of '?' means it could not "
                "be resolved, say so rather than guessing. Recompute every "
                "counting question fresh (via the tool) even if a similar "
                "question was already asked earlier in this conversation - "
                "never reuse or lightly revise a previous answer. "
                "Managers are real people; the data already maps every season to "
                "the correct real manager. Playoff games (type P) are games where "
                "both teams could still win the championship; consolation games "
                "(type C) do not count toward records unless the user asks. Be "
                "concise and conversational, and include the relevant numbers.\n\n"
            ),
        },
        {
            "type": "text",
            "text": "",  # filled with league data below
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        },
    ]

    if "ask_messages" not in st.session_state:
        st.session_state.ask_messages = []

    if st.session_state.ask_messages:
        if st.button("🗑️ Clear chat and start fresh"):
            st.session_state.ask_messages = []
            st.rerun()

    for msg in st.session_state.ask_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("e.g. What year did the ties happen?")
    if question:
        st.session_state.ask_messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        system = [dict(SYSTEM_PROMPT[0]), dict(SYSTEM_PROMPT[1])]
        system[1]["text"] = "# LEAGUE DATA\n" + get_ask_context(league_data.data_fingerprint())

        with st.chat_message("assistant"):
            try:
                # Tool-use loop: Claude may call query_league_data one or more
                # times (e.g. to look something up before answering) before
                # producing its final text. Only the finished text is kept in
                # ask_messages - the tool round-trips don't need to persist.
                api_messages = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.ask_messages
                ]
                with st.spinner("Checking the record books..."):
                    for _ in range(8):  # safety cap on tool-call round-trips
                        response = get_client().messages.create(
                            model="claude-haiku-4-5",
                            max_tokens=2000,
                            system=system,
                            messages=api_messages,
                            tools=[QUERY_TOOL],
                        )
                        if response.stop_reason != "tool_use":
                            break
                        api_messages.append({"role": "assistant", "content": response.content})
                        tool_results = []
                        for block in response.content:
                            if block.type != "tool_use":
                                continue
                            result = run_query_tool(block.input)
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": json.dumps(result),
                                }
                            )
                        api_messages.append({"role": "user", "content": tool_results})
                    else:
                        # Loop exhausted without a final end_turn response - the
                        # last response.content is mid-reasoning (e.g. "Let me
                        # check each season..."), not a real answer. Don't show
                        # it as if it were one.
                        response = None
                if response is None:
                    answer = (
                        "That question needed more lookups than I could finish - "
                        "try breaking it into a narrower question (e.g. one "
                        "season or manager at a time)."
                    )
                else:
                    answer = next(
                        (b.text for b in response.content if b.type == "text"),
                        "Sorry, I couldn't produce an answer.",
                    )
            except anthropic.AuthenticationError:
                answer = (
                    "Your ANTHROPIC_API_KEY appears to be invalid. Double-check "
                    "the value in your .env file and restart the app."
                )
            except anthropic.APIStatusError as exc:
                answer = f"The Claude API returned an error: {exc.message}"
            except anthropic.APIConnectionError:
                answer = "Couldn't reach the Claude API - check your internet connection."
            st.markdown(answer)

        st.session_state.ask_messages.append({"role": "assistant", "content": answer})
