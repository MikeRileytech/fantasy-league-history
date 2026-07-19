"""
League history dashboard.

Run it with:
    streamlit run app.py
"""

import os

import streamlit as st
from dotenv import load_dotenv

import league_data

load_dotenv()

st.set_page_config(page_title="League History", page_icon="🏈", layout="wide")


@st.cache_data
def load_all():
    teams = league_data.load_teams()
    matchups = league_data.load_matchups()
    draft = league_data.load_draft()
    return teams, matchups, draft


try:
    teams, matchups, draft = load_all()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

st.title("🏈 Fantasy League History")
seasons = sorted(teams["season"].unique())
st.caption(f"{seasons[0]}–{seasons[-1]} · {teams['manager'].nunique()} managers")

tab_alltime, tab_seasons, tab_h2h, tab_draft, tab_ask = st.tabs(
    ["All-Time Standings", "Season Browser", "Head-to-Head", "Draft History", "Ask the League"]
)

with tab_alltime:
    st.subheader("Career records by manager")
    st.caption(
        "Grouped by real manager (not ESPN team), using manager_mapping.csv. "
        "Sorted by championships, then win percentage."
    )
    col_po_at, col_cons_at = st.columns(2)
    with col_po_at:
        at_playoffs = st.checkbox("Include playoff games", value=True, key="at_po")
    with col_cons_at:
        at_consolation = st.checkbox("Include consolation games", value=False, key="at_cons")
    at_game_types = ["regular"]
    if at_playoffs:
        at_game_types.append("playoff")
    if at_consolation:
        at_game_types.append("consolation")
    career = league_data.manager_career_standings(teams, matchups, game_types=at_game_types)
    st.dataframe(
        career,
        width='stretch',
        hide_index=True,
        column_config={
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
    col_po, col_cons = st.columns(2)
    with col_po:
        with_playoffs = st.checkbox("Include playoff games", value=True)
    with col_cons:
        with_consolation = st.checkbox("Include consolation games", value=False)
    game_types = ["regular"]
    if with_playoffs:
        game_types.append("playoff")
    if with_consolation:
        game_types.append("consolation")
    grid = league_data.head_to_head(matchups, game_types=game_types)
    st.dataframe(grid, width='stretch')

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
