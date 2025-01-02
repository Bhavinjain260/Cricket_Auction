import time
import streamlit as st
import sqlite3
import os
import pandas as pd
from datetime import datetime
from pathlib import Path

# Constants and Configuration
DB_NAME = "auction.db"
PHOTO_DIR = Path("photos")
LOGO_DIR = Path("logos")
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

# Ensure directories exist
PHOTO_DIR.mkdir(exist_ok=True)
LOGO_DIR.mkdir(exist_ok=True)


class Database:
    def __init__(self, db_name):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Create players table with additional fields
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    photo TEXT,
                    base_price INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    sold_to TEXT,
                    sold_price INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    age INTEGER,
                    stats TEXT
                )
            ''')

            # Create teams table with additional fields
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS teams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    logo TEXT,
                    budget INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create auction_history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS auction_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER,
                    team_id INTEGER,
                    bid_amount INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (player_id) REFERENCES players (id),
                    FOREIGN KEY (team_id) REFERENCES teams (id)
                )
            ''')


class AuctionManager:
    def __init__(self, db):
        self.db = db

    def validate_file(self, file):
        if file is None:
            return True
        if file.size > MAX_UPLOAD_SIZE:
            raise ValueError(f"File size exceeds {MAX_UPLOAD_SIZE / 1024 / 1024}MB limit")
        if Path(file.name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("Invalid file type. Please upload PNG or JPEG files")
        return True

    def save_file(self, file, directory):
        if file is None:
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{file.name}"
        filepath = directory / filename
        with open(filepath, "wb") as f:
            f.write(file.getbuffer())
        return str(filepath)

    def add_team(self, name, logo, budget):
        try:
            self.validate_file(logo)
            logo_path = self.save_file(logo, LOGO_DIR)

            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO teams (name, logo, budget) VALUES (?, ?, ?)",
                    (name, logo_path, budget)
                )
            return True
        except sqlite3.IntegrityError:
            raise ValueError("Team name already exists")
        except Exception as e:
            raise ValueError(f"Error adding team: {str(e)}")

    def add_player(self, name, photo, base_price, player_type, age=None, stats=None):
        try:
            self.validate_file(photo)
            photo_path = self.save_file(photo, PHOTO_DIR)

            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO players 
                       (name, photo, base_price, type, age, stats) 
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (name, photo_path, base_price, player_type, age, stats)
                )
            return True
        except Exception as e:
            raise ValueError(f"Error adding player: {str(e)}")

    def process_bid(self, player_id, team_name, bid_amount):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Check team budget
            cursor.execute("SELECT id, budget FROM teams WHERE name = ?", (team_name,))
            team_data = cursor.fetchone()
            if not team_data or team_data[1] < bid_amount:
                raise ValueError("Insufficient budget")

            team_id = team_data[0]

            # Update player
            cursor.execute(
                "UPDATE players SET sold_to = ?, sold_price = ? WHERE id = ?",
                (team_name, bid_amount, player_id)
            )

            # Update team budget
            cursor.execute(
                "UPDATE teams SET budget = budget - ? WHERE id = ?",
                (bid_amount, team_id)
            )

            # Record in auction history
            cursor.execute(
                "INSERT INTO auction_history (player_id, team_id, bid_amount) VALUES (?, ?, ?)",
                (player_id, team_id, bid_amount)
            )

            return True


class StreamlitUI:
    def __init__(self):
        self.db = Database(DB_NAME)
        self.auction_manager = AuctionManager(self.db)

    def display_home_page(self):
        st.title("🏏 Cricket Auction Management System by Bhavin")

        # Display statistics
        col1, col2, col3, col4 = st.columns(4)

        with self.db.get_connection() as conn:
            total_players = pd.read_sql_query("SELECT COUNT(*) as count FROM players", conn).iloc[0]['count']
            total_teams = pd.read_sql_query("SELECT COUNT(*) as count FROM teams", conn).iloc[0]['count']
            total_sold = \
            pd.read_sql_query("SELECT COUNT(*) as count FROM players WHERE sold_to IS NOT NULL", conn).iloc[0]['count']
            unsold_player = pd.read_sql_query("SELECT COUNT(*) AS unsold_player_count FROM players WHERE sold_to IS "
                                              "NULL AND sold_price IS NULL", conn).iloc[0]



        with col1:
            st.metric("Total Players", total_players)
        with col2:
            st.metric("Total Teams", total_teams)
        with col3:
            st.metric("Players Sold", total_sold)

        with col4:
            st.metric("Unsold Players", unsold_player)

        # Recent transactions
        st.subheader("Recent Transactions")
        with self.db.get_connection() as conn:
            recent = pd.read_sql_query("""
                SELECT p.name as player, p.sold_to as team, p.sold_price as price, p.type
                FROM players p
                WHERE p.sold_to IS NOT NULL
                ORDER BY p.created_at DESC
                LIMIT 5
            """, conn)
            if not recent.empty:
                st.dataframe(recent)
            else:
                st.info("No transactions yet")

    def add_team_page(self):
        st.title("Add Team")
        with st.form("add_team_form"):
            team_name = st.text_input("Team Name")
            logo = st.file_uploader("Team Logo (optional)", type=list(ALLOWED_EXTENSIONS))
            budget = st.number_input("Budget", min_value=0, value=100000)

            submitted = st.form_submit_button("Add Team")
            if submitted:
                try:
                    if not team_name:
                        st.error("Team name is required")
                        return
                    if self.auction_manager.add_team(team_name, logo, budget):
                        st.success("Team added successfully!")
                except ValueError as e:
                    st.error(str(e))

    def add_player_page(self):
        st.title("Add Player")
        with st.form("add_player_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Player Name")
                photo = st.file_uploader("Player Photo (optional)", type=list(ALLOWED_EXTENSIONS))
                base_price = st.number_input("Base Price", min_value=1000)
            with col2:
                player_type = st.selectbox("Player Type", ["Batsman", "Bowler", "All-Rounder", "Wicket-Keeper"])
                age = st.number_input("Age", min_value=15, max_value=50)

            stats = st.text_area("Player Statistics/Description")

            submitted = st.form_submit_button("Add Player")
            if submitted:
                try:
                    if not name or base_price <= 0:
                        st.error("Name and base price are required")
                        return
                    if self.auction_manager.add_player(name, photo, base_price, player_type, age, stats):
                        st.success("Player added successfully!")
                except ValueError as e:
                    st.error(str(e))

    # def auction_page(self):
    #     st.title("Live Auction")
    #
    #     # Initialize session state for current player if not exists
    #     if 'current_player' not in st.session_state:
    #         st.session_state.current_player = None
    #
    #     # Only fetch new player if we don't have one or Pass button is clicked
    #     if st.session_state.current_player is None:
    #         with self.db.get_connection() as conn:
    #             # Modified query to explicitly check for unsold players
    #             random_player = pd.read_sql_query("""
    #                 SELECT id, name, base_price, type, photo, stats, age
    #                 FROM players
    #                 WHERE sold_to IS NULL
    #                 AND sold_price IS NULL
    #                 ORDER BY RANDOM()
    #                 LIMIT 1
    #             """, conn)
    #
    #             if not random_player.empty:
    #                 st.session_state.current_player = random_player.iloc[0].to_dict()
    #             else:
    #                 st.session_state.current_player = None
    #
    #     # Check if there's a current player before proceeding
    #     if st.session_state.current_player is None:
    #         st.warning("No players available for auction")
    #         return
    #
    #     with self.db.get_connection() as conn:
    #         teams = pd.read_sql_query("SELECT name, budget FROM teams", conn)
    #
    #     if teams.empty:
    #         st.warning("No teams available for bidding")
    #         return
    #
    #     col1, col2 = st.columns([2, 1])
    #
    #     with col1:
    #         player_data = st.session_state.current_player
    #         st.header(player_data['name'])
    #
    #         # Display player image if available
    #         if player_data['photo']:
    #             try:
    #                 st.image(player_data['photo'], width=300)
    #             except Exception:
    #                 st.error("Unable to load player image")
    #
    #         # Player details in a clean format
    #         st.subheader("Player Details")
    #         details_col1, details_col2 = st.columns(2)
    #         with details_col1:
    #             st.write(f"**Type:** {player_data['type']}")
    #             st.write(f"**Base Price:** ₹{player_data['base_price']:,}")
    #         with details_col2:
    #             st.write(f"**Age:** {player_data['age']}")
    #
    #         if player_data['stats']:
    #             st.write("**Statistics/Description:**")
    #             st.write(player_data['stats'])
    #
    #     with col2:
    #         st.subheader("Bidding")
    #         team_name = st.selectbox("Select Team", teams['name'])
    #         team_budget = teams[teams['name'] == team_name]['budget'].iloc[0]
    #         st.write(f"**Available Budget:** ₹{team_budget:,}")
    #
    #         # Modified number input with 100 increment
    #         bid_price = st.number_input(
    #             "Bid Amount",
    #             min_value=int(player_data['base_price']),
    #             max_value=int(team_budget),
    #             step=100  # Changed to 100 increment
    #         )
    #
    #         col_pass, col_bid = st.columns(2)
    #         with col_bid:
    #             if st.button("Submit Bid", type="primary"):
    #                 try:
    #                     if self.auction_manager.process_bid(player_data['id'], team_name, bid_price):
    #                         st.success("Bid successful! Player sold.")
    #                         # Clear current player and rerun to get next player
    #                         st.session_state.current_player = None
    #                         time.sleep(1)
    #                         st.rerun()
    #                 except ValueError as e:
    #                     st.error(str(e))
    #
    #         with col_pass:
    #             if st.button("Pass"):
    #                 # Clear current player and rerun to get next player
    #                 st.session_state.current_player = None
    #                 st.rerun()

    def auction_page(self):
        st.title("Live Auction")

        # Initialize session state for current player if not exists
        if 'current_player' not in st.session_state:
            st.session_state.current_player = None

        # Only fetch new player if we don't have one or Pass button is clicked
        if st.session_state.current_player is None:
            with self.db.get_connection() as conn:
                random_player = pd.read_sql_query("""
                    SELECT id, name, base_price, type, photo, stats, age
                    FROM players 
                    WHERE sold_to IS NULL 
                    AND sold_price IS NULL
                    ORDER BY RANDOM()
                    LIMIT 1
                """, conn)

                if not random_player.empty:
                    st.session_state.current_player = random_player.iloc[0].to_dict()
                else:
                    st.session_state.current_player = None

        # Check if there's a current player before proceeding
        if st.session_state.current_player is None:
            st.warning("No players available for auction")
            return

        with self.db.get_connection() as conn:
            teams = pd.read_sql_query("SELECT name, budget FROM teams", conn)

        if teams.empty:
            st.warning("No teams available for bidding")
            return

        # Player Information Section
        player_data = st.session_state.current_player
        st.header(player_data['name'])

        # Display player image if available
        if player_data['photo']:
            try:
                st.image(player_data['photo'], width=300)
            except Exception:
                st.error("Unable to load player image")

        # Player details
        st.subheader("Player Details")
        st.write(f"**Type:** {player_data['type']}")
        st.write(f"**Base Price:** ₹{player_data['base_price']:,}")
        st.write(f"**Age:** {player_data['age']}")

        if player_data['stats']:
            st.write("**Statistics/Description:**")
            st.write(player_data['stats'])

        # Bidding Section
        st.markdown("---")  # Divider
        st.subheader("Bidding")

        # Team selection
        team_name = st.selectbox("Select Team", teams['name'])
        team_budget = teams[teams['name'] == team_name]['budget'].iloc[0]
        st.write(f"**Available Budget:** ₹{team_budget:,}")

        # Bid amount input
        bid_price = st.number_input(
            "Bid Amount",
            min_value=int(player_data['base_price']),
            max_value=int(team_budget),
            step=100
        )

        # Action buttons
        col_pass, col_bid = st.columns(2)
        with col_bid:
            if st.button("Submit Bid", type="primary", use_container_width=True):
                try:
                    if self.auction_manager.process_bid(player_data['id'], team_name, bid_price):
                        st.success("Bid successful! Player sold.")
                        st.session_state.current_player = None
                        time.sleep(1)
                        st.rerun()
                except ValueError as e:
                    st.error(str(e))

        with col_pass:
            if st.button("Pass", use_container_width=True):
                st.session_state.current_player = None
                st.rerun()


    def view_team_rosters_page(self):
        st.title("Team Rosters")

        # Changed radio button options
        view_type = st.radio("Select View", ["Current Roster", "Unsold Players"], horizontal=True)

        with self.db.get_connection() as conn:
            teams = pd.read_sql_query("SELECT name FROM teams", conn)

        if teams.empty:
            st.warning("No teams available")
            return

        if view_type == "Current Roster":
            team_name = st.selectbox("Select Team", teams['name'])


        with self.db.get_connection() as conn:
            if view_type == "Current Roster":
                # Current roster view
                roster = pd.read_sql_query("""
                    SELECT 
                        name as "Player Name",
                        type as "Role",
                        age as "Age",
                        sold_price as "Purchase Amount",
                        created_at as "Acquired Date"
                    FROM players
                    WHERE sold_to = ?
                    ORDER BY type, name
                """, conn, params=(team_name,))

                if not roster.empty:
                    roster["Purchase Amount"] = roster["Purchase Amount"].apply(lambda x: f"₹{x:,}")
                    roster["Acquired Date"] = pd.to_datetime(roster["Acquired Date"]).dt.strftime("%Y-%m-%d -%r")
            else:
                # Unsold players view
                roster = pd.read_sql_query("""
                    SELECT 
                        name as "Player Name",
                        type as "Role",
                        age as "Age",
                        base_price as "Base Price"
                    FROM players
                    WHERE sold_to IS NULL 
                    AND sold_price IS NULL
                    ORDER BY type, base_price DESC
                """, conn)

                if not roster.empty:
                    roster["Base Price"] = roster["Base Price"].apply(lambda x: f"₹{x:,}")

            # Get team budget info only for Current Roster view
            if view_type == "Current Roster":
                budget_info = pd.read_sql_query("""
                    SELECT budget, 
                           (SELECT SUM(sold_price) FROM players WHERE sold_to = t.name) as spent
                    FROM teams t
                    WHERE name = ?
                """, conn, params=(team_name,))

                # Display budget metrics
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Remaining Budget", f"₹{budget_info['budget'].iloc[0]:,}")
                with col2:
                    spent = budget_info['spent'].iloc[0] or 0
                    st.metric("Total Spent", f"₹{spent:,}")

        # Display roster with appropriate message
        if not roster.empty:
            st.dataframe(roster, use_container_width=True)
        else:
            if view_type == "Current Roster":
                st.info("No players in this team yet")
            else:
                st.info("No unsold players available")

    # def view_team_rosters_page(self):
    #     st.title("Team Rosters")
    #
    #     # Add view selection
    #     view_type = st.radio("Select View", ["Current Roster", "All Transactions"], horizontal=True)
    #
    #     with self.db.get_connection() as conn:
    #         teams = pd.read_sql_query("SELECT name FROM teams", conn)
    #
    #     if teams.empty:
    #         st.warning("No teams available")
    #         return
    #
    #     team_name = st.selectbox("Select Team", teams['name'])
    #
    #     with self.db.get_connection() as conn:
    #         if view_type == "Current Roster":
    #             # Current roster view
    #             roster = pd.read_sql_query("""
    #                 SELECT
    #                     name as "Player Name",
    #                     type as "Role",
    #                     age as "Age",
    #                     sold_price as "Purchase Amount",
    #                     created_at as "Acquired Date"
    #                 FROM players
    #                 WHERE sold_to = ?
    #                 ORDER BY type, name
    #             """, conn, params=(team_name,))
    #
    #             if not roster.empty:
    #                 roster["Purchase Amount"] = roster["Purchase Amount"].apply(lambda x: f"₹{x:,}")
    #                 roster["Acquired Date"] = pd.to_datetime(roster["Acquired Date"]).dt.strftime("%Y-%m-%d")
    #         else:
    #             # All transactions view
    #             roster = pd.read_sql_query("""
    #                 SELECT
    #                     p.name as "Player Name",
    #                     p.type as "Role",
    #                     p.base_price as "Base Price",
    #                     p.sold_price as "Final Bid",
    #                     CASE
    #                         WHEN p.sold_to IS NOT NULL THEN 'Sold'
    #                         ELSE 'Unsold'
    #                     END as "Status",
    #                     p.created_at as "Auction Date"
    #                 FROM players p
    #                 WHERE p.sold_to = ? OR (
    #                     ? IN (
    #                         SELECT DISTINCT sold_to
    #                         FROM players
    #                         WHERE sold_to IS NOT NULL
    #                     )
    #                     AND p.sold_to IS NULL
    #                 )
    #                 ORDER BY p.created_at DESC
    #             """, conn, params=(team_name, team_name))
    #
    #             if not roster.empty:
    #                 roster["Base Price"] = roster["Base Price"].apply(lambda x: f"₹{x:,}")
    #                 roster["Final Bid"] = roster["Final Bid"].apply(lambda x: f"₹{x:,}" if x else "N/A")
    #                 roster["Auction Date"] = pd.to_datetime(roster["Auction Date"]).dt.strftime("%Y-%m-%d")
    #
    #         # Get team budget
    #         budget_info = pd.read_sql_query("""
    #             SELECT budget,
    #                    (SELECT SUM(sold_price) FROM players WHERE sold_to = t.name) as spent
    #             FROM teams t
    #             WHERE name = ?
    #         """, conn, params=(team_name,))
    #
    #     # Display budget metrics
    #     col1, col2 = st.columns(2)
    #     with col1:
    #         st.metric("Remaining Budget", f"₹{budget_info['budget'].iloc[0]:,}")
    #     with col2:
    #         spent = budget_info['spent'].iloc[0] or 0
    #         st.metric("Total Spent", f"₹{spent:,}")
    #
    #     # Display roster
    #     if not roster.empty:
    #         st.dataframe(roster, use_container_width=True)
    #     else:
    #         st.info("No players in this team yet")

    # def auction_page(self):
    #     st.title("Live Auction")
    #
    #     with self.db.get_connection() as conn:
    #         players = pd.read_sql_query("""
    #             SELECT id, name, base_price, type
    #             FROM players
    #             WHERE sold_to IS NULL
    #         """, conn)
    #         teams = pd.read_sql_query("SELECT name, budget FROM teams", conn)
    #
    #     if players.empty:
    #         st.warning("No players available for auction")
    #         return
    #
    #     if teams.empty:
    #         st.warning("No teams available for bidding")
    #         return
    #
    #     col1, col2 = st.columns([2, 1])
    #
    #     with col1:
    #         selected_player = st.selectbox(
    #             "Select Player",
    #             players['id'].tolist(),
    #             format_func=lambda x: f"{players[players['id'] == x]['name'].iloc[0]} "
    #                                   f"(Base: {players[players['id'] == x]['base_price'].iloc[0]})"
    #         )
    #
    #         player_data = players[players['id'] == selected_player].iloc[0]
    #         st.write(f"Type: {player_data['type']}")
    #
    #     with col2:
    #         team_name = st.selectbox("Select Team", teams['name'])
    #         team_budget = teams[teams['name'] == team_name]['budget'].iloc[0]
    #         st.write(f"Available Budget: {team_budget:,}")
    #
    #         bid_price = st.number_input(
    #             "Bid Amount",
    #             min_value=int(player_data['base_price']),
    #             max_value=int(team_budget)
    #         )
    #
    #         if st.button("Submit Bid"):
    #             try:
    #                 if self.auction_manager.process_bid(selected_player, team_name, bid_price):
    #                     st.success("Bid successful! Player sold.")
    #                     st.rerun()
    #             except ValueError as e:
    #                 st.error(str(e))
    #
    # def view_team_rosters_page(self):
    #     st.title("Team Rosters")
    #
    #     with self.db.get_connection() as conn:
    #         teams = pd.read_sql_query("SELECT name FROM teams", conn)
    #
    #     if teams.empty:
    #         st.warning("No teams available")
    #         return
    #
    #     team_name = st.selectbox("Select Team", teams['name'])
    #
    #     with self.db.get_connection() as conn:
    #         roster = pd.read_sql_query("""
    #             SELECT name, type, age, sold_price
    #             FROM players
    #             WHERE sold_to = ?
    #             ORDER BY type, name
    #         """, conn, params=(team_name,))
    #
    #         budget_info = pd.read_sql_query("""
    #             SELECT budget
    #             FROM teams
    #             WHERE name = ?
    #         """, conn, params=(team_name,))
    #
    #     st.metric("Remaining Budget", f"₹{budget_info['budget'].iloc[0]:,}")
    #
    #     if not roster.empty:
    #         st.dataframe(roster)
    #     else:
    #         st.info("No players in this team yet")

    def run(self):
        st.sidebar.title("Navigation")
        pages = {
            "Home": self.display_home_page,
            "Add Team": self.add_team_page,
            "Add Player": self.add_player_page,
            "Live Auction": self.auction_page,
            "Team Rosters": self.view_team_rosters_page
        }

        page = st.sidebar.radio("Go to", list(pages.keys()))
        pages[page]()


if __name__ == "__main__":
    app = StreamlitUI()
    app.run()