"""
League history dashboard.

Run it with:
    streamlit run app.py
"""

import importlib
import os

import streamlit as st
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

tab_alltime, tab_trophies, tab_seasons, tab_h2h, tab_tx, tab_draft, tab_charts, tab_ask = st.tabs(
    ["All-Time Standings", "Trophies", "Season Browser", "Head-to-Head", "Transactions", "Draft History", "Charts", "Ask the League"]
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
    st.caption(
        "📊 Showing the essentials. Tap the column-visibility icon "
        "(top-right of the table, next to search/download) to add Seasons, "
        "First/Last year, or PF/PA."
    )
    st.dataframe(
        career,
        width='stretch',
        hide_index=True,
        column_order=[
            "logo",
            "manager",
            "championships",
            "wins",
            "losses",
            "ties",
            "win_pct",
        ],
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
    season = st.selectbox("Season", seasons, index=len(seasons) - 1)
    st.subheader(f"{season} final standings")
    standings = league_data.season_standings(teams, season)
    champ = standings.iloc[0]
    st.success(f"🏆 Champion: **{champ['manager']}** ({champ['team_name']})")
    st.dataframe(
        standings,
        width='stretch',
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
        st.markdown("### 🤝 Trades")
        st.warning(
            "ESPN's API only returns full trade detail for trades involving "
            "the account that imported the data (currently Mike's), plus all "
            "2018 trades. Other managers' trades exist in ESPN's records but "
            "aren't retrievable with one login - if other managers share "
            "their ESPN credentials, their trades can be imported too.",
            icon="⚠️",
        )
        trades = league_data.executed_trades(transactions)
        trade_season = st.selectbox(
            "Season",
            ["All"] + sorted(trades["season"].unique().tolist(), reverse=True),
            key="trade_season",
        )
        shown_trades = trades if trade_season == "All" else trades[trades["season"] == trade_season]
        st.dataframe(
            shown_trades.drop(columns=["date"]),
            width='stretch',
            hide_index=True,
            column_config={
                "season": st.column_config.NumberColumn("Season", format="%d"),
                "week": st.column_config.NumberColumn("Week", format="%d"),
                "manager_a": "Manager",
                "received_a": "Received",
                "manager_b": "Manager ",
                "received_b": "Received ",
            },
        )

        st.divider()
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
    col1, col2 = st.columns(2)
    with col1:
        draft_season = st.selectbox(
            "Season", ["All"] + seasons, index=0, key="draft_season"
        )
    with col2:
        search = st.text_input("Search player or manager")

    table = league_data.draft_table(draft)
    if draft_season != "All":
        table = table[table["season"] == draft_season]
    if search:
        mask = table["player_name"].str.contains(search, case=False, na=False) | table[
            "manager"
        ].str.contains(search, case=False, na=False)
        table = table[mask]
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
    def get_ask_context():
        return league_data.build_ask_context(teams, matchups, draft)

    @st.cache_resource
    def get_client():
        return anthropic.Anthropic(api_key=api_key)

    SYSTEM_PROMPT = [
        {
            "type": "text",
            "text": (
                "You are the historian for a fantasy football league. Answer "
                "questions using ONLY the league data below. If the data does not "
                "contain the answer, say so - never guess or invent results. "
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

    for msg in st.session_state.ask_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("e.g. What year did the ties happen?")
    if question:
        st.session_state.ask_messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        system = [dict(SYSTEM_PROMPT[0]), dict(SYSTEM_PROMPT[1])]
        system[1]["text"] = "# LEAGUE DATA\n" + get_ask_context()

        with st.chat_message("assistant"):
            try:
                with st.spinner("Checking the record books..."):
                    response = get_client().messages.create(
                        model="claude-haiku-4-5",
                        max_tokens=2000,
                        system=system,
                        messages=[
                            {"role": m["role"], "content": m["content"]}
                            for m in st.session_state.ask_messages
                        ],
                    )
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
