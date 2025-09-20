# Beeminder Meditation Sync

Automated GitHub Action that syncs meditation data between Beeminder goals.

## Features

- Maintains a local "source of truth" database for meditation tracking
- Syncs data between the database and a Beeminder goal
- Automatically detects qualifying early morning meditations (5 AM - 8:30 AM, ≥35 minutes)
- Runs daily at 8:35 AM New York time

## Setup

1. **Fork/Clone this repository**

2. **Set up GitHub Secrets:**
   Go to Settings → Secrets and variables → Actions, and add:
   - `BEEMINDER_USERNAME`: Your Beeminder username
   - `BEEMINDER_AUTH_TOKEN`: Your Beeminder auth token
   - `BEEMINDER_GOAL_SLUG`: Target goal slug (e.g., "meditate-early")

3. **Enable GitHub Actions:**
   Go to the Actions tab and enable workflows

4. **Test the workflow:**
   You can manually trigger the workflow from the Actions tab

## How It Works

1. **Database Management:** Creates/maintains a JSON database in `data/meditation_sot.json`
2. **Data Sync:** Ensures the Beeminder goal matches the local database exactly
3. **Meditation Detection:** Checks the `meditatev4` goal for qualifying meditations
4. **Automatic Updates:** Adds qualifying meditations as +1 datapoints

## Manual Testing

Run locally with:
```bash
pip install -r requirements.txt
python scripts/beeminder_sync.py
```

## Security Note

Never commit your `.env` file. Always use GitHub Secrets for production.