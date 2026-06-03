import streamlit as st
import psycopg2
import json
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="World Cup 2026 Pool", page_icon="⚽", layout="wide")

# Official 2026 World Cup Groups
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

# --- POINT VALUES CONFIGURATION ---
POINTS_CONFIG = {
    "group_advancer": 2,      # Per correct team (Max 64)
    "r32_winner": 4,          # Per correct team (Max 64)
    "r16_winner": 8,          # Per correct team (Max 64)
    "qf_winner": 12,          # Per correct team (Max 48)
    "sf_winner": 16,          # Per correct team (Max 32)
    "champion": 25,           # Correct winner
    "pre_finalist": 15,       # Per correct finalist picked pre-tournament (Max 30)
    "player_of_tournament": 20,
    "top_scorer": 20
}

# --- DATABASE OPERATIONS ---

def get_db_connection():
    return psycopg2.connect(**st.secrets["postgres"])

def save_prediction_to_db(data):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = """
            INSERT INTO world_cup_predictions 
            (friend_name, group_advancers, r32_winners, r16_winners, qf_winners, sf_winners, champion, pre_tournament_finalists, player_of_tournament, top_scorer)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """
        cur.execute(query, (
            data['name'], json.dumps(data['advancers']), json.dumps(data['r32']),
            json.dumps(data['r16']), json.dumps(data['qf']), json.dumps(data['sf']),
            data['champion'], json.dumps(data['pre_finalists']), data['pot'], data['top_scorer']
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Database write error: {e}")
        return False

def load_all_predictions():
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM world_cup_predictions ORDER BY submitted_at DESC;", conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Database read error: {e}")
        return pd.DataFrame()

def load_actual_results():
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM world_cup_actual WHERE id = 1;", conn)
        conn.close()
        if not df.empty:
            return df.iloc[0].to_dict()
    except Exception as e:
        st.error(f"Error loading live results: {e}")
    return {}

def update_actual_results(data):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = """
            UPDATE world_cup_actual SET 
            group_advancers = %s, r32_winners = %s, r16_winners = %s, qf_winners = %s, 
            sf_winners = %s, champion = %s, player_of_tournament = %s, top_scorer = %s
            WHERE id = 1;
        """
        cur.execute(query, (
            json.dumps(data['advancers']), json.dumps(data['r32']), json.dumps(data['r16']),
            json.dumps(data['qf']), json.dumps(data['sf']), data['champion'], data['pot'], data['top_scorer']
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Failed to update actual results: {e}")
        return False

# --- CALCULATION ENGINE LOGIC ---

def safe_parse_json(val):
    if isinstance(val, list): return set(val)
    if isinstance(val, str):
        try: return set(json.loads(val))
        except: return set()
    return set()

def calculate_score(row, actual):
    if not actual: return 0
    
    score = 0
    # 1. Group Stage
    pred_adv = safe_parse_json(row['group_advancers'])
    act_adv = safe_parse_json(actual.get('group_advancers', []))
    score += len(pred_adv.intersection(act_adv)) * POINTS_CONFIG["group_advancer"]
    
    # 2. Knockout Stages
    stages = [('r32_winners', 'r32_winner'), ('r16_winners', 'r16_winner'), ('qf_winners', 'qf_winner'), ('sf_winners', 'sf_winner')]
    for col_name, config_key in stages:
        pred_k = safe_parse_json(row[col_name])
        act_k = safe_parse_json(actual.get(col_name, []))
        score += len(pred_k.intersection(act_k)) * POINTS_CONFIG[config_key]
        
    # 3. Champion
    if row['champion'] and row['champion'] == actual.get('champion'):
        score += POINTS_CONFIG["champion"]
        
    # 4. Pre-Tournament Lookahead Finalists (Checked against actual sf_winners/finalists)
    pred_fin = safe_parse_json(row['pre_tournament_finalists'])
    act_fin = safe_parse_json(actual.get('sf_winners', []))
    score += len(pred_fin.intersection(act_fin)) * POINTS_CONFIG["pre_finalist"]
    
    # 5. Award Categories (Case-insensitive matching)
    if actual.get('player_of_tournament') and str(row['player_of_tournament']).lower().strip() == str(actual['player_of_tournament']).lower().strip():
        score += POINTS_CONFIG["player_of_tournament"]
    if actual.get('top_scorer') and str(row['top_scorer']).lower().strip() == str(actual['top_scorer']).lower().strip():
        score += POINTS_CONFIG["top_scorer"]
        
    return score

# --- APPLICATION TABS ---

tab1, tab2, tab3 = st.tabs(["📝 Submit Predictions", "📊 Leaderboard & Dashboard", "⚙️ Admin Center"])

# ==========================================
# TAB 1: SUBMISSION FORM
# ==========================================
with tab1:
    st.markdown("### Lock in your tournament bracket")
    friend_name = st.text_input("Enter your name:", placeholder="e.g., Nikos K.", key="submit_name")

    if friend_name:
        st.header("1. Group Stage Progressors")
        selected_advancers = []
        cols = st.columns(3)
        for idx, (group_name, teams) in enumerate(GROUPS.items()):
            with cols[idx % 3]:
                st.subheader(group_name)
                for team in teams:
                    if st.checkbox(team, key=f"adv_{group_name}_{team}"):
                        selected_advancers.append(team)
                        
        st.metric("Total Selected Teams", f"{len(selected_advancers)} / 32")

        if len(selected_advancers) == 32:
            st.header("2. Knockout Bracket Phase")
            r32_winners = st.multiselect("Pick Round of 32 Winners:", selected_advancers)
            
            r16_winners = []
            if len(r32_winners) == 16:
                r16_winners = st.multiselect("Pick Round of 16 Winners:", r32_winners)
                
            qf_winners = []
            if len(r16_winners) == 8:
                qf_winners = st.multiselect("Pick Quarterfinal Winners:", r16_winners)

            sf_winners = []
            champion = ""
            if len(qf_winners) == 4:
                sf_winners = st.multiselect("Pick Finalists:", qf_winners)
                if len(sf_winners) == 2:
                    champion = st.radio("🏆 Absolute Champion:", sf_winners)
            
            st.header("3. Standalone & Player Predictions")
            pre_tournament_finalists = st.multiselect("Predict the 2 Finalists:", ALL_TEAMS, max_selections=2)
            player_of_tournament = st.text_input("Player of the Tournament:")
            top_scorer = st.text_input("Top Scorer:")
            
            ready_to_submit = (
                len(selected_advancers) == 32 and len(r32_winners) == 16 and len(r16_winners) == 8 and 
                len(qf_winners) == 4 and len(sf_winners) == 2 and champion != "" and 
                len(pre_tournament_finalists) == 2 and player_of_tournament != "" and top_scorer != ""
            )
            
            if ready_to_submit:
                if st.button("🚀 Submit My Predictions", type="primary"):
                    payload = {
                        "name": friend_name, "advancers": selected_advancers, "r32": r32_winners,
                        "r16": r16_winners, "qf": qf_winners, "sf": sf_winners, "champion": champion,
                        "pre_finalists": pre_tournament_finalists, "pot": player_of_tournament, "top_scorer": top_scorer
                    }
                    if save_prediction_to_db(payload):
                        st.success(f"Awesome, {friend_name}! Predictions saved.")
                        st.balloons()
        else:
            st.warning("Please select exactly 32 teams from the group stage to unlock the bracket stages.")

# ==========================================
# TAB 2: LIVE LEADERBOARD & DASHBOARD
# ==========================================
with tab2:
    df_preds = load_all_predictions()
    actual_results = load_actual_results()
    
    if df_preds.empty:
        st.info("No predictions submitted yet.")
    else:
        # Calculate scores for all users dynamically
        df_preds['Current Score'] = df_preds.apply(lambda row: calculate_score(row, actual_results), axis=1)
        
        # Sort by points descending to formulate the Leaderboard
        leaderboard_df = df_preds.sort_values(by='Current Score', ascending=False).reset_index(drop=True)
        leaderboard_df.index += 1  # Standard 1-based ranking index
        
        st.subheader("🏆 Live Standings Leaderboard")
        display_leaderboard = pd.DataFrame({
            "Rank": leaderboard_df.index,
            "Competitor": leaderboard_df["friend_name"],
            "Total Points": leaderboard_df["Current Score"],
            "Predicted Champion": leaderboard_df["champion"],
            "Golden Boot Pick": leaderboard_df["top_scorer"]
        })
        st.dataframe(display_leaderboard, use_container_width=True, hide_index=True)
        
        st.write("---")
        # Trends Analysis
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.markdown("**Group Champion Distributions:**")
            champ_counts = df_preds["champion"].value_counts().reset_index()
            st.plotly_chart(px.bar(champ_counts, x="champion", y="count", text_auto=True), use_container_width=True)
        with col_chart2:
            st.markdown("**Top Scorer Distributions:**")
            boot_counts = df_preds["top_scorer"].value_counts().reset_index()
            st.plotly_chart(px.bar(boot_counts, x="top_scorer", y="count", text_auto=True), use_container_width=True)

# ==========================================
# TAB 3: ADMIN OVERRIDE CENTER
# ==========================================
with tab3:
    st.subheader("🛡️ Master Tournament Controller")
    st.caption("Update real-life tournament outcomes here to instantly recalculate points across the entire system.")
    
    # Simple UI security layer
    admin_pass = st.text_input("Enter Admin Access Code:", type="password")
    if admin_pass == st.secrets.get("admin_password", "worldcup2026"):
        current_actual = load_actual_results()
        
        st.markdown("### Update Real-World Progress")
        act_adv = st.multiselect("Real Group Stage Progressors (Select 32):", ALL_TEAMS, default=list(safe_parse_json(current_actual.get('group_advancers', []))))
        act_r32 = st.multiselect("Real Round of 32 Winners (Select 16):", act_adv, default=list(safe_parse_json(current_actual.get('r32_winners', []))))
        act_r16 = st.multiselect("Real Round of 16 Winners (Select 8):", act_r32, default=list(safe_parse_json(current_actual.get('r16_winners', []))))
        act_qf  = st.multiselect("Real Quarterfinal Winners (Select 4):", act_r16, default=list(safe_parse_json(current_actual.get('qf_winners', []))))
        act_sf  = st.multiselect("Real Finalists (Select 2):", act_qf, default=list(safe_parse_json(current_actual.get('sf_winners', []))))
        
        act_champ = st.selectbox("Real Verified Champion:", [""] + list(act_sf), index=0 if not current_actual.get('champion') else list(act_sf).index(current_actual['champion']) + 1 if current_actual['champion'] in act_sf else 0)
        
        act_pot = st.text_input("Official Tournament MVP (Golden Ball):", value=current_actual.get('player_of_tournament', ''))
        act_boot = st.text_input("Official Golden Boot Winner:", value=current_actual.get('top_scorer', ''))
        
        if st.button("💾 Commit Real Results & Re-Score Pool", type="primary"):
            admin_payload = {
                "advancers": act_adv, "r32": act_r32, "r16": act_r16, "qf": act_qf,
                "sf": act_sf, "champion": act_champ, "pot": act_pot, "top_scorer": act_boot
            }
            if update_actual_results(admin_payload):
                st.success("Database engine updated. Standings have been completely recalculated!")
                st.cache_data.clear() # Clear cached leaderboard values
    elif admin_pass != "":
        st.error("Invalid passcode.")
