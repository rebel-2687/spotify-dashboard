# spotify-dashboard


# Spotify Streaming Stats Dashboard (Local JSON)

A streamlit dashboard that reads and analyzes a json file of a Spotify user's listening history using the data provided by a GDPR request to help users make sense of their data. This app runs fully locally.

## What it shows

- Top **tracks**
- Top **artists**
- Top **albums**
- Date-range filtered stats (default start date is **2026-01-01** for YTD)

## Input data

Upload one of the following in the app:

- A single Spotify streaming history **JSON** file
- A **ZIP** containing one or more history JSON files

Supported schemas include:

- Older account export fields: `endTime`, `artistName`, `trackName`, `msPlayed`
- Extended export fields: `ts`, `master_metadata_*`, `ms_played`

If album data is not present in your JSON, album values are left blank in results.

## Setup

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Usage

1. Launch the app.
2. Upload your JSON (or ZIP).
3. Choose **Tracks**, **Artists**, or **Albums**.
4. Set start/end dates to filter (for 2026 YTD, use start date `2026-01-01` and no end date).
5. Adjust **Top N** to control how many rows are shown.

## Notes

- No Spotify API credentials are required.
- Data is processed locally in memory during the session.
- The file should be called "StreamingHistory_music-0.json" from the Account Data zipfile that you receive.
