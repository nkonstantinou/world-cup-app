import streamlit as st
import psycopg2
import json
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="World Cup 2026 Pool", page_icon="⚽", layout="wide")

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

# --- DATABASE ENGINE ---
def get_db_connection():
    return psycopg2.connect(**st.secrets["postgres"])

def get_user_data(name):
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM world_cup_predictions WHERE LOWER(friend_name) = LOWER(%s);", conn, params=[name])
        conn.close()
        return df.iloc[0].to_dict() if not df.empty else None
    except:
        return None

def save_initial_predictions(data):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = """
            INSERT INTO world_cup_predictions 
            (friend_name, group_advancers, r32_winners, r16_winners, qf_winners, sf_winners, champion, pre_tournament_finalists, player_of_tournament, top_scorer)
            VALUES (%s, %s, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '', %s, %s, %s)
            ON CONFLICT (friend_name) DO NOTHING;
        """
        cur.execute(query, (data['name'], json.dumps(data['advancers']), json.dumps(data['pre_finalists']), data['pot'], data['top_scorer']))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        st.error(f"Save error: {e}"); return False

def update_round_predictions(name, round_col, winners_list):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = f"UPDATE world_cup_predictions SET {round_col} = %s WHERE LOWER(friend_name) = LOWER(%s);"
        cur.execute(query, (json.dumps(winners_list), name))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        st.error(f"Update error: {e}"); return False

def save_active_matchups(round_id, pairings):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = """
            INSERT INTO world_cup_active_matchups (round_id, pairings) VALUES (%s, %s)
            ON CONFLICT (round_id) DO UPDATE SET pairings = EXCLUDED.pairings;
        """
        cur.execute(query, (round_id, json.dumps(pairings)))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        st.error(f"Matchup save error: {e}"); return False

def load_active_matchups(round_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT pairings FROM world_cup_active_matchups WHERE round_id = %s;", (round_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return json.loads(row[0]) if row else []
    except:
        return []

# --- APP LAYOUT ---
tab1, tab2, tab3 = st.tabs(["📝 User Portal", "📊 Leaderboard", "⚙️ Admin Center"])

# ==========================================
# TAB 1: USER PORTAL (DYNAMIC SUBMISSIONS)
# ==========================================
with tab1:
    st.header("⚽ World Cup Prediction Center")
    user_name = st.text_input("Enter your unique name to continue:", placeholder="e.g., Nikos K.").strip()

    if user_name:
        existing_record = get_user_data(user_name)
        
        if not existing_record:
            st.success(f"Welcome {user_name}! Let's lock in your Pre-Tournament setup.")
            st.markdown("### 1. Group Stage Qualifications")
            st.info("Rule: Select exactly **the top 2 teams** from each group. The leftovers will automatically become wildcard options.")
            
            selected_top2 = []
            leftover_options = []
            
            cols = st.columns(3)
            for idx, (group, teams) in enumerate(GROUPS.items()):
                with cols[idx % 3]:
                    st.subheader(group)
                    chosen = st.multiselect(f"Qualifiers from {group}", teams, max_selections=2, key=f"sub_{group}")
                    if len(chosen) == 2:
                        selected_top2.extend(chosen)
                        leftover_options.extend([t for t in teams if t not in chosen])
            
            st.write("---")
            st.markdown("### 2. The 8 Best Third-Placed Wildcards")
            final_wildcards = []
            if len(selected_top2) == 24:
                final_wildcards = st.multiselect("Select exactly 8 best 3rd-placed teams to advance:", leftover_options, max_selections=8)
            else:
                st.warning("Please select exactly 2 teams from all 12 groups above to compute the third-place options.")
                
            st.write("---")
            st.markdown("### 3. Absolute Tournament Forecasts")
            pre_finalists = st.multiselect("Predict the 2 teams that will reach the Grand Final:", ALL_TEAMS, max_selections=2)
            pot = st.text_input("Tournament MVP (Golden Ball):")
            top_scorer = st.text_input("Top Goal Scorer (Golden Boot):")
            
            if len(selected_top2) == 24 and len(final_wildcards) == 8 and len(pre_finalists) == 2 and pot and top_scorer:
                if st.button("🚀 Lock In My Tournament Setup", type="primary"):
                    payload = {
                        "name": user_name, "advancers": selected_top2 + final_wildcards,
                        "pre_finalists": pre_finalists, "pot": pot, "top_scorer": top_scorer
                    }
                    if save_initial_predictions(payload):
                        st.success("Setup complete! Your pre-tournament predictions are securely stored.")
                        st.balloons()
                        st.rerun()
            else:
                st.caption("Complete all structural rules above to activate submission.")
        
        else:
            st.subheader(f"👋 Welcome back, {user_name}!")
            st.info("Your pre-tournament choices are locked. Below is the live knockout round open for prediction right now:")
            
            # Look for active rounds published by admin
            active_round = None
            round_labels = {"R32": ("Round of 32", "r32_winners"), "R16": ("Round of 16", "r16_winners"), "QF": ("Quarterfinals", "qf_winners"), "SF": ("Semifinals", "sf_winners")}
            
            for r_id, (label, col) in round_labels.items():
                if len(load_active_matchups(r_id)) > 0:
                    active_round = (r_id, label, col)
            
            if active_round:
                r_id, label, col_name = active_round
                st.markdown(f"### ⚡ Live Prediction: {label}")
                matchups = load_active_matchups(r_id)
                
                user_winners = []
                cols = st.columns(2)
                for idx, match in enumerate(matchups):
                    with cols[idx % 2]:
                        choice = st.radio(f"Match {idx+1}: Who wins?", match, key=f"live_m_{r_id}_{idx}")
                        user_winners.append(choice)
                
                if st.button(f"💾 Submit {label} Picks", type="primary"):
                    if update_round_predictions(user_name, col_name, user_winners):
                        st.success(f"Your {label} predictions have been safely updated!")
                        st.balloons()
            else:
                st.success("There are no active knockout rounds waiting for submission right now. Enjoy the matches!")

# ==========================================
# TAB 2: LEADERBOARD (Omitted for brevity, code hooks logic natively)
# ==========================================
with tab2:
    st.subheader("🏆 Live Standings Pool")
    st.caption("Once data pours in, your group leaderboard scores will generate right here.")

# ==========================================
# TAB 3: ADMIN CENTER (MANAGE MATCHUPS)
# ==========================================
with tab3:
    st.header("🛡️ Matchmaker & Controller")
    admin_pass = st.text_input("Enter Admin Access Code:", type="password", key="admin_key")
    if admin_pass == st.secrets.get("admin_password", "worldcup2026"):
        
        target_round = st.selectbox("Select Knockout Phase to Setup Matchups:", ["None", "R32", "R16", "QF", "SF"])
        
        if target_round != "None":
            slots = {"R32": 16, "R16": 8, "QF": 4, "SF": 2}[target_round]
            st.markdown(f"#### Configure Pairing Nodes for {target_round} ({slots} Matches)")
            
            current_pairings = load_active_matchups(target_round)
            saved_pairings = []
            
            for i in range(slots):
                st.markdown(f"**Match {i+1}**")
                c1, c2 = st.columns(2)
                default_t1 = current_pairings[i][0] if i < len(current_pairings) else ALL_TEAMS[0]
                default_t2 = current_pairings[i][1] if i < len(current_pairings) else ALL_TEAMS[1]
                
                with c1: t1 = st.selectbox(f"Match {i+1} Team 1", ALL_TEAMS, index=ALL_TEAMS.index(default_t1), key=f"adm_t1_{i}")
                with c2: t2 = st.selectbox(f"Match {i+1} Team 2", ALL_TEAMS, index=ALL_TEAMS.index(default_t2), key=f"adm_t2_{i}")
                saved_pairings.append([t1, t2])
                
            if st.button("📢 Publish Matchups to Friends", type="primary"):
                if save_active_matchups(target_round, saved_pairings):
                    st.success(f"Matchups for {target_round} successfully published live!")
