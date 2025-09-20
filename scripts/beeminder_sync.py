#!/usr/bin/env python3
"""
Beeminder Meditation Sync Script
Syncs meditation data between Beeminder goals and a local source of truth database
"""

import os
import json
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
import pytz

# Load environment variables manually from .env file
def load_env():
    env_path = '.env'
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env()

# Configuration
BEEMINDER_USERNAME = os.getenv('BEEMINDER_USERNAME', 'zarathustra')
BEEMINDER_AUTH_TOKEN = os.getenv('BEEMINDER_AUTH_TOKEN')
BEEMINDER_GOAL_SLUG = os.getenv('BEEMINDER_GOAL_SLUG', 'meditate-early')
BEEMINDER_SOURCE_GOAL = os.getenv('BEEMINDER_SOURCE_GOAL_SLUG', 'meditatev4')

# Database configuration
DB_PATH = Path('data/meditation_sot.json')

# Timezone configuration
NYC_TZ = pytz.timezone('America/New_York')

class BeeminderAPI:
    """Handle Beeminder API interactions"""

    def __init__(self, username: str, auth_token: str):
        self.username = username
        self.auth_token = auth_token
        self.base_url = 'https://www.beeminder.com/api/v1'

    def get_goal_data(self, goal_slug: str) -> List[Dict]:
        """Get all datapoints for a specific goal with pagination support"""
        all_datapoints = []
        page = 1
        per_page = 300  # Maximum allowed by Beeminder API

        while True:
            url = f"{self.base_url}/users/{self.username}/goals/{goal_slug}/datapoints.json"
            params = {
                'auth_token': self.auth_token,
                'page': page,
                'per_page': per_page
            }

            try:
                response = requests.get(url, params=params)
                response.raise_for_status()
                page_data = response.json()

                if not page_data:  # No more data
                    break

                all_datapoints.extend(page_data)

                # If we got less than per_page, we're done
                if len(page_data) < per_page:
                    break

                page += 1
                print(f"Fetched page {page-1} for {goal_slug}: {len(page_data)} datapoints")

            except requests.exceptions.RequestException as e:
                print(f"Error fetching goal data for {goal_slug} (page {page}): {e}")
                break

        print(f"Total datapoints fetched for {goal_slug}: {len(all_datapoints)}")
        return all_datapoints

    def add_datapoint(self, goal_slug: str, value: float, timestamp: int, comment: str = "") -> bool:
        """Add a datapoint to a goal"""
        url = f"{self.base_url}/users/{self.username}/goals/{goal_slug}/datapoints.json"
        data = {
            'auth_token': self.auth_token,
            'value': value,
            'timestamp': timestamp,
            'comment': comment
        }

        try:
            response = requests.post(url, data=data)
            response.raise_for_status()
            print(f"Added datapoint to {goal_slug}: value={value}, timestamp={timestamp}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error adding datapoint to {goal_slug}: {e}")
            return False

    def delete_datapoint(self, goal_slug: str, datapoint_id: str) -> bool:
        """Delete a datapoint from a goal"""
        url = f"{self.base_url}/users/{self.username}/goals/{goal_slug}/datapoints/{datapoint_id}.json"
        params = {'auth_token': self.auth_token}

        try:
            response = requests.delete(url, params=params)
            response.raise_for_status()
            print(f"Deleted datapoint {datapoint_id} from {goal_slug}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error deleting datapoint {datapoint_id} from {goal_slug}: {e}")
            return False

class MeditationDatabase:
    """Handle local source of truth database operations"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.data = self._load_or_create()

    def _load_or_create(self) -> Dict:
        """Load existing database or create a new one"""
        if self.db_path.exists():
            print(f"Loading existing database from {self.db_path}")
            with open(self.db_path, 'r') as f:
                return json.load(f)
        else:
            print(f"Creating new database at {self.db_path}")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            initial_data = {
                'datapoints': [],
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
            # Save initial data directly
            with open(self.db_path, 'w') as f:
                json.dump(initial_data, f, indent=2)
            return initial_data

    def save(self):
        """Save database to file"""
        self.data['last_updated'] = datetime.now(timezone.utc).isoformat()
        with open(self.db_path, 'w') as f:
            json.dump(self.data, f, indent=2)
        print(f"Database saved to {self.db_path}")

    def get_datapoints(self) -> List[Dict]:
        """Get all datapoints from database"""
        return self.data.get('datapoints', [])

    def add_datapoint(self, value: float, timestamp: int, comment: str = ""):
        """Add a datapoint to the database"""
        datapoint = {
            'value': value,
            'timestamp': timestamp,
            'comment': comment,
            'id': f"local_{timestamp}_{value}"
        }
        self.data['datapoints'].append(datapoint)
        print(f"Added datapoint to local database: {datapoint}")

    def datapoint_exists(self, timestamp: int, value: float) -> bool:
        """Check if a datapoint already exists"""
        for dp in self.data['datapoints']:
            if dp['timestamp'] == timestamp and dp['value'] == value:
                return True
        return False

def sync_beeminder_with_database(api: BeeminderAPI, db: MeditationDatabase, goal_slug: str):
    """Sync Beeminder goal with local database"""
    print(f"\nSyncing {goal_slug} with local database...")

    # Get current data from both sources
    beeminder_data = api.get_goal_data(goal_slug)
    local_data = db.get_datapoints()

    # Create lookup sets for comparison (using timestamp and value as unique identifier)
    beeminder_set = {(dp['timestamp'], dp['value']) for dp in beeminder_data}
    local_set = {(dp['timestamp'], dp['value']) for dp in local_data}

    # Find differences
    to_delete_from_beeminder = beeminder_set - local_set
    to_add_to_beeminder = local_set - beeminder_set

    # Delete datapoints from Beeminder that aren't in local database
    for timestamp, value in to_delete_from_beeminder:
        # Find the datapoint ID
        for dp in beeminder_data:
            if dp['timestamp'] == timestamp and dp['value'] == value:
                api.delete_datapoint(goal_slug, dp['id'])
                break

    # Add datapoints to Beeminder that are in local database
    for timestamp, value in to_add_to_beeminder:
        # Find the comment from local data
        comment = ""
        for dp in local_data:
            if dp['timestamp'] == timestamp and dp['value'] == value:
                comment = dp.get('comment', '')
                break
        api.add_datapoint(goal_slug, value, timestamp, comment)

    print(f"Sync complete. Deleted {len(to_delete_from_beeminder)} datapoints, added {len(to_add_to_beeminder)} datapoints.")

def check_and_add_qualifying_meditation(api: BeeminderAPI, db: MeditationDatabase):
    """Check meditatev4 goal for qualifying meditations and add them if found"""
    print(f"\nChecking {BEEMINDER_SOURCE_GOAL} for qualifying meditations...")

    # Get current NYC time
    nyc_now = datetime.now(NYC_TZ)
    today_5am = nyc_now.replace(hour=5, minute=0, second=0, microsecond=0)
    today_830am = nyc_now.replace(hour=8, minute=30, second=0, microsecond=0)

    # Get meditation data from source goal
    meditation_data = api.get_goal_data(BEEMINDER_SOURCE_GOAL)

    for datapoint in meditation_data:
        # Convert timestamp to NYC time
        meditation_time = datetime.fromtimestamp(datapoint['timestamp'], tz=NYC_TZ)
        meditation_date = meditation_time.date()
        today_date = nyc_now.date()

        # Check if meditation is from today
        if meditation_date != today_date:
            continue

        # Check if meditation was between 5 AM and 8:30 AM
        if not (today_5am <= meditation_time <= today_830am):
            continue

        # Check if meditation is at least 35 minutes
        if datapoint['value'] < 35:
            continue

        # Check if we've already recorded this meditation
        if db.datapoint_exists(datapoint['timestamp'], 1):
            print(f"Qualifying meditation already recorded: {meditation_time}")
            continue

        # Add qualifying meditation to database and goal
        print(f"Found qualifying meditation: {datapoint['value']} minutes at {meditation_time}")
        comment = f"Early meditation: {datapoint['value']} minutes at {meditation_time.strftime('%H:%M')}"

        # Add to local database
        db.add_datapoint(1, datapoint['timestamp'], comment)

        # Add to Beeminder goal
        api.add_datapoint(BEEMINDER_GOAL_SLUG, 1, datapoint['timestamp'], comment)

        print(f"Added qualifying meditation to database and {BEEMINDER_GOAL_SLUG}")

        # Save database after adding
        db.save()

        # Only count one qualifying meditation per day
        break

def main():
    """Main execution function"""
    print("=" * 50)
    print("Beeminder Meditation Sync")
    print(f"Time: {datetime.now(NYC_TZ)}")
    print("=" * 50)

    # Validate environment variables
    if not BEEMINDER_AUTH_TOKEN:
        raise ValueError("BEEMINDER_AUTH_TOKEN not set in environment variables")

    # Initialize components
    api = BeeminderAPI(BEEMINDER_USERNAME, BEEMINDER_AUTH_TOKEN)
    db = MeditationDatabase(DB_PATH)

    # Step 2: Sync Beeminder goal with local database
    sync_beeminder_with_database(api, db, BEEMINDER_GOAL_SLUG)

    # Step 3: Check for qualifying meditations
    check_and_add_qualifying_meditation(api, db)

    # Save final state
    db.save()

    print("\n" + "=" * 50)
    print("Sync completed successfully!")
    print("=" * 50)

if __name__ == "__main__":
    main()