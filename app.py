import streamlit as st
import psycopg2
import json
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

st.set_page_config(page_title="World Cup 2026 Pool", page_icon="⚽", layout="wide")

# Timezone Configurations
CYPRUS_TZ = ZoneInfo("Europe/Nicosia")
TOURNAMENT_START = datetime(2026, 6, 11, 15, 0, tzinfo=CYPRUS_TZ)

GROUPS = {
    "Group A": ["Mexico", "South Africa", "Korea Republic", "Czechia"],
    "Group B": ["Canada", "Switzerland", "Qatar", "Bosnia and Herzegovina"],
    "Group C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "Group D": ["United States", "Paraguay", "Australia", "Türkiye"],
    "Group E": ["Germany", "Curaçao", "Côte d'Ivoire", "Ecuador"],
    "Group F": ["Netherlands", "Japan", "Tunisia", "Sweden"],
    "Group G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "Group H": ["Spain", "Cabo Verde", "Saudi Arabia", "Uruguay"],
    "Group I": ["France", "Senegal", "Norway", "Iraq"],
    "Group J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "Group K": ["Portugal", "Uzbekistan", "Colombia", "Congo DR"],
    "Group L": ["England", "Croatia", "Ghana", "Panama"]
}
ALL_TEAMS = sorted([team for sublist in GROUPS.values() for team in sublist])

# Programmatic Fixture Generator (Cached so it runs exactly ONCE, saving massive CPU cycles)
@st.cache_data
def get_all_fixtures():
    MATCH_SLOTS = [15, 18, 21, 0]
    fixtures = []
    combo_list = []
    for group_name, teams in GROUPS.items():
        combos = [
            (teams[0], teams[1]), (teams[2], teams[3]),
            (teams[0], teams[2]), (teams[1], teams[3]),
            (teams[3], teams[0]), (teams[1], teams[2])
        ]
        for t1, t2 in combos:
            combo_list.append((group_name, t1, t2))
            
    start_date = datetime(2026, 6, 11, tzinfo=CYPRUS_TZ)
    for idx, (group_name, t1, t2) in enumerate(combo_list):
        day_offset = idx // 4
        slot_idx = idx % 4
        hour = MATCH_SLOTS[slot_idx]
        kickoff = (start_date + timedelta(days=day_offset)).replace(hour=hour, minute=0, second=0, microsecond=0)
        fixtures.append({"id": f"M{idx+1}", "group": group_name, "t1": t1, "t2": t2, "kickoff": kickoff})
    return fixtures

GROUP_MATCHES = get_all_fixtures()

# --- FAST DATABASE ACCESS ---
def get_db_connection():
    return psycopg2.connect(**st.secrets["postgres"])

def get_user_data(name):
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM world_cup_predictions WHERE LOWER(friend_name) = LOWER(%s);", conn, params=[name])
        conn.close()
        return df.iloc[0].to_dict() if not df.empty else None
    except: return None

def save_user_profile(name, champion, pot, top_scorer, advancers, match_preds):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = """
            INSERT INTO world_cup_predictions 
            (friend_name, champion, player_of_tournament, top_scorer, group_advancers, group_match_predictions, r32_winners, r16_winners, qf_winners, sf_winners, pre_tournament_finalists)
            VALUES (%s, %s, %s, %s, %s, %s, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb)
            ON CONFLICT (friend_name) DO UPDATE SET 
                champion = EXCLUDED.champion, player_of_tournament = EXCLUDED.player_of_tournament,
                top_scorer = EXCLUDED.top_scorer, group_advancers = EXCLUDED.group_advancers,
                group_match_predictions = EXCLUDED.group_match_predictions;
        """
        cur.execute(query, (name, champion, pot, top_scorer, json.dumps(advancers), json.dumps(match_preds)))
        conn.commit(); cur.close(); conn.close()
        return True
    except: return False

# --- UI APPARATUS ---
current_time = datetime.now(CYPRUS_TZ)
tab1, tab2, tab3 = st.tabs(["📝 Prediction Portal", "📊 Live Leaderboard", "⚙️ Admin Core"])

with tab1:
    st.header("⚽ World Cup 1,000-Point Predictor")
    
    # Step 1: User logs in outside the form. This happens only once.
    user_name = st.text_input("Enter your name to load your interactive workspace:", placeholder="e.g., Nikos K.").strip()
    
    if user_name:
        is_tournament_started = current_time >= TOURNAMENT_START
        user_record = get_user_data(user_name)
        existing_preds = json.loads(user_record['group_match_predictions']) if user_record and user_record.get('group_match_predictions') else {}
        
        # Open the master batched form container
        with st.form("master_prediction_form"):
            st.info("⚡ Pro-tip: You can click all your answers instantly now without lag. Remember to scroll down and click 'Save all Predictions' at the bottom when you're done!")
            
            # PART 1: AWARDS
            st.markdown("### 🏆 Part 1: Elite Pre-Tournament Awards")
            if is_tournament_started:
                chosen_champ = user_record.get('champion', '')
                chosen_pot = user_record.get('player_of_tournament', '')
                chosen_boot = user_record.get('top_scorer', '')
                st.disabled(st.text_input("Absolute Champion:", value=chosen_champ))
            else:
                default_champ = user_record.get('champion', ALL_TEAMS[0]) if user_record else ALL_TEAMS[0]
                chosen_champ = st.selectbox("Predict Absolute Champion (80 pts):", ALL_TEAMS, index=ALL_TEAMS.index(default_champ))
                chosen_pot = st.text_input("Predict Golden Ball Winner (50 pts):", value=user_record.get('player_of_tournament', '') if user_record else '')
                chosen_boot = st.text_input("Predict Golden Boot Winner (50 pts):", value=user_record.get('top_scorer', '') if user_record else '')

            st.markdown("---")
            
            # PART 2: THE 72 MATCHES
            st.markdown("### 📅 Part 2: Chronological Group Stage Predictions (2 pts each)")
            updated_match_preds = existing_preds.copy()
            
            for match in GROUP_MATCHES:
                m_id = match["id"]
                t1, t2 = match["t1"], match["t2"]
                kickoff_time = match["kickoff"]
                is_match_locked = current_time >= kickoff_time
                
                col1, col2 = st.columns([2, 3])
                with col1:
                    lock_status = "🔒 Locked" if is_match_locked else "⏳ Active"
                    st.markdown(f"**{m_id}: {t1} vs {t2}** ({lock_status})")
                    st.caption(f"Kickoff: {kickoff_time.strftime('%d %b, %H:%M')}")
                with col2:
                    saved_vote = existing_preds.get(m_id, "Draw")
                    options = [f"{t1} Win", "Draw", f"{t2} Win"]
                    def_idx = options.index(saved_vote) if saved_vote in options else 1
                    
                    vote = st.radio(
                        f"M_{m_id}", options, index=def_idx, horizontal=True,
                        label_visibility="collapsed", disabled=is_match_locked, key=f"form_v_{m_id}"
                    )
                    # Accumulate selection data array cleanly 
                    if not is_match_locked:
                        updated_match_preds[m_id] = vote
            
            st.markdown("---")
            
            # PART 3: ADVANCEMENT PATHWAYS
            st.markdown("### 🔀 Part 3: Group Stage Advancement (3 pts per team)")
            if is_tournament_started:
                saved_advancers = json.loads(user_record['group_advancers']) if user_record and user_record.get('group_advancers') else []
                st.caption(f"Your Locked Bracket Selection: {', '.join(saved_advancers)}")
            else:
                saved_advancers = []
                leftover_pool = []
                cols = st.columns(3)
                for idx, (group, teams) in enumerate(GROUPS.items()):
                    with cols[idx % 3]:
                        st.markdown(f"**{group}**")
                        selected = st.multiselect(f"Top 2 from {group}", teams, max_selections=2, key=f"form_grp_{group}")
                        if len(selected) == 2:
                            saved_advancers.extend(selected)
                            leftover_pool.extend([t for t in teams if t not in selected])
                
                st.markdown("**8 Best Third-Place Wildcards**")
                wildcards = st.multiselect("Pick 8 standard third-place teams to fill the 32-team knockout field:", sorted(leftover_pool), max_selections=8, key="form_wildcards")
                if len(wildcards) == 8:
                    saved_advancers.extend(wildcards)

            # THE FORM SUBMIT KEYSTONE BUTTON
            st.markdown("---")
            submit_profile = st.form_submit_button("🚀 Save All My Predictions", type="primary")
            
            if submit_profile:
                if is_tournament_started:
                    # Rolling mode updates only unlocked match cells
                    if update_only_matches(user_name, updated_match_preds):
                        st.success("Upcoming match updates saved successfully!")
                else:
                    # Pre-tournament strict checking modes
                    if len(saved_advancers) == 32 and chosen_champ and chosen_pot and chosen_boot:
                        if save_user_profile(user_name, chosen_champ, chosen_pot, chosen_boot, saved_advancers, updated_match_preds):
                            st.success("Incredible! Your entire tournament profile map is safely locked in.")
                            st.balloons()
                    else:
                        st.error("Validation Halt: You must select exactly 32 advancing teams (2 per group + 8 wildcards) before saving.")

# ==========================================
# (Tabs 2 & 3 code remain intact natively here)
# ==========================================
