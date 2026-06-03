import streamlit as st
import psycopg2
import json
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

st.set_page_config(page_title="World Cup 2026 Pool", page_icon="⚽", layout="wide")

# Timezone Configurations
CYPRUS_TZ = ZoneInfo("Europe/Nicosia")
TOURNAMENT_START = datetime(2026, 6, 11, 15, 0, tzinfo=CYPRUS_TZ) # Opening match kick-off time

# Official Tournament Groups
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

# --- PROGRAMMATIC FIXTURE GENERATOR ---
# Automatically schedules all 72 match combinations chronologically at premium watch times (Cyprus local time)
MATCH_SLOTS = [15, 18, 21, 0]
GROUP_MATCHES = []
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
    
    match_date = start_date + timedelta(days=day_offset)
    kickoff = datetime(match_date.year, match_date.month, match_date.day, hour, 0, tzinfo=CYPRUS_TZ)
    
    GROUP_MATCHES.append({
        "id": f"M{idx+1}",
        "group": group_name,
        "t1": t1,
        "t2": t2,
        "kickoff": kickoff
    })

# --- DATABASE INTERFACES ---
def get_db_connection():
    return psycopg2.connect(**st.secrets["postgres"])

def get_user_data(name):
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM world_cup_predictions WHERE LOWER(friend_name) = LOWER(%s);", conn, params=[name])
        conn.close()
        return df.iloc[0].to_dict() if not df.empty else None
    except: return None

def load_all_predictions():
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM world_cup_predictions ORDER BY friend_name ASC;", conn)
        conn.close()
        return df
    except: return pd.DataFrame()

def load_actual_results():
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM world_cup_actual WHERE id = 1;", conn)
        conn.close()
        return df.iloc[0].to_dict() if not df.empty else {}
    except: return {}

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

def update_only_matches(name, match_preds):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE world_cup_predictions SET group_match_predictions = %s WHERE LOWER(friend_name) = LOWER(%s);", (json.dumps(match_preds), name))
        conn.commit(); cur.close(); conn.close()
        return True
    except: return False

def update_actual_results(data):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = """
            UPDATE world_cup_actual SET 
            group_match_results = %s, group_advancers = %s, r32_winners = %s, r16_winners = %s, 
            qf_winners = %s, sf_winners = %s, champion = %s, player_of_tournament = %s, top_scorer = %s
            WHERE id = 1;
        """
        cur.execute(query, (
            json.dumps(data['match_results']), json.dumps(data['advancers']), json.dumps(data['r32']),
            json.dumps(data['r16']), json.dumps(data['qf']), json.dumps(data['sf']),
            data['champion'], data['pot'], data['top_scorer']
        ))
        conn.commit(); cur.close(); conn.close()
        return True
    except: return False

# --- SCORING MATHEMATICS CALCULATOR ---
def safe_parse_json(val):
    if isinstance(val, list): return set(val)
    if isinstance(val, str):
        try: return set(json.loads(val))
        except: return set()
    return set()

def calculate_score(row, actual):
    if not actual: return 0
    score = 0
    
    # 1. 72 Group Stage Matches (2 points each -> Max 144)
    pred_matches = row.get('group_match_predictions', {})
    if isinstance(pred_matches, str):
        try: pred_matches = json.loads(pred_matches)
        except: pred_matches = {}
    act_matches = actual.get('group_match_results', {})
    if isinstance(act_matches, str):
        try: act_matches = json.loads(act_matches)
        except: act_matches = {}
        
    for m_id, act_res in act_matches.items():
        if pred_matches.get(m_id) == act_res:
            score += 2
            
    # 2. Group Stage Progressors (3 points each -> Max 96)
    score += len(safe_parse_json(row['group_advancers']).intersection(safe_parse_json(actual.get('group_advancers', [])))) * 3
    
    # 3. Knockout Stages
    score += len(safe_parse_json(row['r32_winners']).intersection(safe_parse_json(actual.get('r32_winners', [])))) * 10 # Max 160
    score += len(safe_parse_json(row['r16_winners']).intersection(safe_parse_json(actual.get('r16_winners', [])))) * 20 # Max 160
    score += len(safe_parse_json(row['qf_winners']).intersection(safe_parse_json(actual.get('qf_winners', [])))) * 35   # Max 140
    score += len(safe_parse_json(row['sf_winners']).intersection(safe_parse_json(actual.get('sf_winners', [])))) * 60   # Max 120
    
    # 4. Absolute Champion (80 points)
    if row['champion'] and row['champion'] == actual.get('champion'):
        score += 80
        
    # 5. Awards (50 points each -> Max 100)
    if actual.get('player_of_tournament') and str(row['player_of_tournament']).lower().strip() == str(actual['player_of_tournament']).lower().strip():
        score += 50
    if actual.get('top_scorer') and str(row['top_scorer']).lower().strip() == str(actual['top_scorer']).lower().strip():
        score += 50
        
    return score

# --- SYSTEM PANELS ---
current_time = datetime.now(CYPRUS_TZ)
st.caption(f"🕒 Cyprus Local Time: {current_time.strftime('%Y-%m-%d %H:%M')}")

tab1, tab2, tab3 = st.tabs(["📝 Prediction Portal", "📊 Live Leaderboard", "⚙️ Admin Core"])

# ==========================================
# TAB 1: USER PREDICTION PORTAL
# ==========================================
with tab1:
    st.header("⚽ World Cup 1,000-Point Predictor")
    user_name = st.text_input("Enter your name to load/create your profile:", placeholder="e.g., Nikos K.").strip()
    
    if user_name:
        is_tournament_started = current_time >= TOURNAMENT_START
        user_record = get_user_data(user_name)
        existing_preds = json.loads(user_record['group_match_predictions']) if user_record and user_record.get('group_match_predictions') else {}
        
        # ----------------------------------
        # PART 1: ELITE AWARDS (HARD LOCK ON TOURNAMENT KICKOFF)
        # ----------------------------------
        st.subheader("🏆 Part 1: Elite Pre-Tournament Awards")
        if is_tournament_started:
            st.warning("🔒 Selections locked at tournament kickoff.")
            chosen_champ = user_record.get('champion', '') if user_record else ''
            chosen_pot = user_record.get('player_of_tournament', '') if user_record else ''
            chosen_boot = user_record.get('top_scorer', '') if user_record else ''
            st.write(f"**Your Champion:** {chosen_champ} | **Golden Ball:** {chosen_pot} | **Golden Boot:** {chosen_boot}")
        else:
            st.info("⌛ Locks on June 11th at 15:00 Cyprus Time.")
            default_champ = user_record.get('champion', ALL_TEAMS[0]) if user_record else ALL_TEAMS[0]
            chosen_champ = st.selectbox("Predict Absolute Champion (80 pts):", ALL_TEAMS, index=ALL_TEAMS.index(default_champ))
            chosen_pot = st.text_input("Predict Golden Ball Winner (50 pts):", value=user_record.get('player_of_tournament', '') if user_record else '')
            chosen_boot = st.text_input("Predict Golden Boot Winner (50 pts):", value=user_record.get('top_scorer', '') if user_record else '')

        st.write("---")
        
        # ----------------------------------
        # PART 2: INDIVIDUAL 72 GROUP MATCHES (ROLLING LOCK)
        # ----------------------------------
        st.subheader("📅 Part 2: Chronological Group Stage Predictions (2 pts each)")
        updated_match_preds = existing_preds.copy()
        
        with st.container():
            for match in GROUP_MATCHES:
                m_id = match["id"]
                t1, t2 = match["t1"], match["t2"]
                kickoff_time = match["kickoff"]
                is_match_locked = current_time >= kickoff_time
                
                col1, col2 = st.columns([2, 3])
                with col1:
                    lock_icon = "🔒 Locked" if is_match_locked else "⏳ Active"
                    st.markdown(f"**{m_id}: {t1} vs {t2}** ({lock_icon})")
                    st.caption(f"Kickoff: {kickoff_time.strftime('%d %b, %H:%M')}")
                with col2:
                    saved_vote = existing_preds.get(m_id, None)
                    options = [f"{t1} Win", "Draw", f"{t2} Win"]
                    def_idx = options.index(saved_vote) if saved_vote in options else 1
                    
                    vote = st.radio(
                        f"M_{m_id}", options, index=def_idx, horizontal=True,
                        label_visibility="collapsed", disabled=is_match_locked, key=f"v_{m_id}"
                    )
                    if not is_match_locked:
                        updated_match_preds[m_id] = vote
                st.write("")

        st.write("---")
        
        # ----------------------------------
        # PART 3: GROUP ADVANCEMENT (HARD LOCK ON TOURNAMENT KICKOFF)
        # ----------------------------------
        st.subheader("🔀 Part 3: Group Stage Advancement (3 pts per team)")
        if is_tournament_started:
            st.warning("🔒 Advancement paths are locked.")
            saved_advancers = json.loads(user_record['group_advancers']) if user_record and user_record.get('group_advancers') else []
            st.write(f"**Your Progressing Bracket Selection:** {', '.join(saved_advancers)}")
        else:
            saved_advancers = []
            leftover_pool = []
            cols = st.columns(3)
            for idx, (group, teams) in enumerate(GROUPS.items()):
                with cols[idx % 3]:
                    st.markdown(f"**{group}**")
                    selected = st.multiselect(f"Top 2 for {group}", teams, max_selections=2, key=f"grp_{group}")
                    if len(selected) == 2:
                        saved_advancers.extend(selected)
                        leftover_pool.extend([t for t in teams if t not in selected])
            
            st.markdown("**8 Best Third-Place Wildcards**")
            wildcards = st.multiselect("Pick 8 standard third-place teams to fill the 32-team knockout field:", sorted(leftover_pool), max_selections=8)
            if len(wildcards) == 8:
                saved_advancers.extend(wildcards)

        # ----------------------------------
        # SUBMIT / SAVE COMMAND ENGINES
        # ----------------------------------
        st.write("---")
        if not is_tournament_started:
            if st.button("🚀 Save Entire Tournament Profile", type="primary"):
                if len(saved_advancers) == 32 and chosen_champ and chosen_pot and chosen_boot:
                    if save_user_profile(user_name, chosen_champ, chosen_pot, chosen_boot, saved_advancers, updated_match_preds):
                        st.success("Success! Full profile saved.")
                        st.balloons()
                else:
                    st.error("Error: Ensure you've picked 32 advancing teams and filled all award parameters.")
        else:
            if st.button("💾 Save Match Prediction Changes", type="primary"):
                if update_only_matches(user_name, updated_match_preds):
                    st.success("Your changes to upcoming matches have been successfully updated.")
                    st.rerun()

# ==========================================
# TAB 2: LIVE LEADERBOARD DASHBOARD
# ==========================================
with tab2:
    st.header("🏆 Group Standings Leaderboard")
    df_all = load_all_predictions()
    actual_res = load_actual_results()
    
    if df_all.empty:
        st.info("Leaderboard is empty. Waiting for users to register.")
    else:
        df_all['Total Points'] = df_all.apply(lambda row: calculate_score(row, actual_res), axis=1)
        leaderboard = df_all.sort_values(by='Total Points', ascending=False).reset_index(drop=True)
        leaderboard.index += 1
        
        display_board = pd.DataFrame({
            "Rank": leaderboard.index,
            "Player": leaderboard["friend_name"],
            "Score / 1000": leaderboard["Total Points"],
            "Picked Champion": leaderboard["champion"]
        })
        st.dataframe(display_board, use_container_width=True, hide_index=True)

# ==========================================
# TAB 3: MASTER ADMIN CONTROLLER
# ==========================================
with tab3:
    st.header("🛡️ Admin Match Result Input Panel")
    admin_pass = st.text_input("Enter Master Code:", type="password")
    if admin_pass == st.secrets.get("admin_password", "worldcup2026"):
        st.success("Access Granted.")
        act = load_actual_results()
        saved_match_results = json.loads(act['group_match_results']) if act and act.get('group_match_results') else {}
        
        st.markdown("### 1. Verify 72 Group Match Outcomes")
        updated_actual_matches = saved_match_results.copy()
        
        for match in GROUP_MATCHES:
            m_id = match["id"]
            t1, t2 = match["t1"], match["t2"]
            opts = ["Not Played", f"{t1} Win", "Draw", f"{t2} Win"]
            cur_val = saved_match_results.get(m_id, "Not Played")
            def_i = opts.index(cur_val) if cur_val in opts else 0
            
            res = st.selectbox(f"{m_id}: {t1} vs {t2}", opts, index=def_i, key=f"adm_m_{m_id}")
            if res != "Not Played":
                updated_actual_matches[m_id] = res
                
        st.markdown("### 2. Verify Knockout Phase Advancers")
        act_adv = st.multiselect("Real-world Group Progressors (32):", ALL_TEAMS, default=list(safe_parse_json(act.get('group_advancers', []))))
        act_r32 = st.multiselect("Real R32 Winners (16):", act_adv, default=list(safe_parse_json(act.get('r32_winners', []))))
        act_r16 = st.multiselect("Real R16 Winners (8):", act_r32, default=list(safe_parse_json(act.get('r16_winners', []))))
        act_qf  = st.multiselect("Real QF Winners (4):", act_r16, default=list(safe_parse_json(act.get('qf_winners', []))))
        act_sf  = st.multiselect("Real Finalists (2):", act_qf, default=list(safe_parse_json(act.get('sf_winners', []))))
        act_ch  = st.selectbox("Real Verified Champion:", [""] + list(act_sf), index=0 if not act.get('champion') else list(act_sf).index(act['champion'])+1 if act['champion'] in act_sf else 0)
        
        act_pot = st.text_input("Official Golden Ball:", value=act.get('player_of_tournament', ''))
        act_boot = st.text_input("Official Golden Boot:", value=act.get('top_scorer', ''))
        
        if st.button("📢 Commit & Recalculate Standings", type="primary"):
            payload = {
                "match_results": updated_actual_matches, "advancers": act_adv, "r32": act_r32,
                "r16": act_r16, "qf": act_qf, "sf": act_sf, "champion": act_ch, "pot": act_pot, "top_scorer": act_boot
            }
            if update_actual_results(payload):
                st.success("Leaderboard updated seamlessly!")
                st.cache_data.clear()
