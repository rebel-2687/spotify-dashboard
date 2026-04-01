import io
import json
import zipfile
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st


APP_TITLE = "Spotify Streaming Stats (Local JSON)"
DEFAULT_YTD_START = date(2026, 1, 1)


def _format_ms(ms: int) -> str:
    if not isinstance(ms, int):
        return "-"
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"

def _parse_ts(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    # Export timestamps can look like:
    # - Extended streaming history: "2026-01-02T13:45:10Z"
    # - Older account export: "2025-02-17 05:40" (endTime)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass

    try:
        # Treat as local-unknown; we store as UTC for consistent filtering.
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _history_row_to_fields(row: dict) -> dict | None:
    """
    Normalize one streaming-history row from Spotify export.
    Supports common keys from "Extended streaming history" JSON.
    """
    ts = _parse_ts(row.get("ts") or row.get("endTime"))
    if ts is None:
        return None

    ms_played = row.get("ms_played") if "ms_played" in row else row.get("msPlayed")
    try:
        ms_played_int = int(ms_played) if ms_played is not None else 0
    except (TypeError, ValueError):
        ms_played_int = 0

    track = (
        row.get("master_metadata_track_name")
        or row.get("trackName")
        or row.get("track_name")
        or row.get("track")
    )
    artist = (
        row.get("master_metadata_album_artist_name")
        or row.get("artistName")
        or row.get("artist_name")
        or row.get("artist")
    )
    album = (
        row.get("master_metadata_album_album_name")
        or row.get("albumName")
        or row.get("album_name")
        or row.get("album")
    )
    track_uri = row.get("spotify_track_uri") or row.get("master_metadata_track_uri") or row.get("track_uri")

    if not track or not artist:
        # Skip podcasts/unknown rows (export includes non-music items sometimes).
        return None

    return {
        "ts": ts,
        "ms_played": ms_played_int,
        "track": str(track),
        "artist": str(artist),
        "album": str(album) if album else "",
        "track_uri": str(track_uri) if track_uri else "",
    }


def _load_history_from_uploaded(uploaded: st.runtime.uploaded_file_manager.UploadedFile) -> pd.DataFrame:
    """
    Accepts Spotify export either as:
    - ZIP containing one or more Streaming_History*.json files
    - A single JSON file containing a list of rows
    """
    name = (uploaded.name or "").lower()
    raw = uploaded.getvalue()

    rows: list[dict] = []

    def _consume_json_bytes(b: bytes) -> None:
        nonlocal rows
        try:
            data = json.loads(b.decode("utf-8"))
        except Exception:
            return
        if isinstance(data, list):
            rows.extend([r for r in data if isinstance(r, dict)])

    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for info in z.infolist():
                if not info.filename.lower().endswith(".json"):
                    continue
                # Heuristic: focus on streaming history JSONs
                fn = info.filename.lower()
                if "streaming" not in fn and "history" not in fn:
                    continue
                _consume_json_bytes(z.read(info))
    else:
        _consume_json_bytes(raw)

    normalized = []
    for r in rows:
        nr = _history_row_to_fields(r)
        if nr:
            normalized.append(nr)

    if not normalized:
        return pd.DataFrame(columns=["ts", "ms_played", "track", "artist", "album", "track_uri"])

    df = pd.DataFrame(normalized)
    # Ensure timezone-aware, comparable timestamps (UTC).
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"])
    return df


def aggregates_between(
    history: pd.DataFrame, start_utc: datetime, end_utc: datetime | None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if history.empty:
        empty_tracks = pd.DataFrame(columns=["rank", "track", "artist", "album", "minutes", "ms_played"])
        empty_artists = pd.DataFrame(columns=["rank", "artist", "minutes", "ms_played"])
        empty_albums = pd.DataFrame(columns=["rank", "album", "artist", "minutes", "ms_played"])
        return empty_tracks, empty_artists, empty_albums

    # Normalize types for safe comparison.
    if "ts" not in history.columns:
        return aggregates_between(pd.DataFrame(columns=["ts", "ms_played", "track", "artist", "album", "track_uri"]), start_utc, end_utc)

    h0 = history.copy()
    h0["ts"] = pd.to_datetime(h0["ts"], utc=True, errors="coerce")
    h0 = h0.dropna(subset=["ts"])

    start_ts = pd.Timestamp(start_utc)
    if start_ts.tz is None:
        start_ts = start_ts.tz_localize("UTC")
    else:
        start_ts = start_ts.tz_convert("UTC")

    end_ts = None
    if end_utc is not None:
        end_ts = pd.Timestamp(end_utc)
        if end_ts.tz is None:
            end_ts = end_ts.tz_localize("UTC")
        else:
            end_ts = end_ts.tz_convert("UTC")

    h = h0[h0["ts"] >= start_ts].copy()
    if end_utc is not None:
        h = h[h["ts"] < end_ts].copy()
    if h.empty:
        return aggregates_between(pd.DataFrame(columns=history.columns), start_utc, end_utc)

    h["minutes"] = (h["ms_played"] / 60000.0).round(2)

    tracks = (
        h.groupby(["track", "artist", "album"], dropna=False)["ms_played"]
        .sum()
        .reset_index()
        .sort_values("ms_played", ascending=False)
    )
    tracks["minutes"] = (tracks["ms_played"] / 60000.0).round(2)
    tracks.insert(0, "rank", range(1, len(tracks) + 1))

    artists = (
        h.groupby(["artist"], dropna=False)["ms_played"]
        .sum()
        .reset_index()
        .sort_values("ms_played", ascending=False)
    )
    artists["minutes"] = (artists["ms_played"] / 60000.0).round(2)
    artists.insert(0, "rank", range(1, len(artists) + 1))

    albums = (
        h.groupby(["album", "artist"], dropna=False)["ms_played"]
        .sum()
        .reset_index()
        .sort_values("ms_played", ascending=False)
    )
    albums["minutes"] = (albums["ms_played"] / 60000.0).round(2)
    albums.insert(0, "rank", range(1, len(albums) + 1))

    return tracks, artists, albums


def _bar_chart(
    df: pd.DataFrame,
    *,
    label_col: str,
    value_col: str,
    title: str,
    max_rows: int = 30,
) -> None:
    if df.empty:
        st.info("No data to chart.")
        return

    view = df.head(max_rows)[[label_col, value_col]].copy()
    view = view.set_index(label_col)
    st.caption(title)
    st.bar_chart(view, y=value_col, horizontal=True)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)

    st.caption("Upload your Spotify streaming history export (JSON or ZIP) to explore your listening stats.")

    with st.sidebar:
        st.subheader("Controls")
        st.caption("Upload Spotify “Extended streaming history” (ZIP or JSON). Processed locally.")
        uploaded = st.file_uploader("Streaming history export", type=["zip", "json"])
        view = st.radio("View", options=["Tracks", "Artists", "Albums"], horizontal=False)
        start_date = st.date_input("Start date", value=DEFAULT_YTD_START)
        end_date_enabled = st.checkbox("Set an end date", value=False)
        end_date = None
        if end_date_enabled:
            end_date = st.date_input("End date (exclusive)", value=date.today())
        limit = st.slider("Show top N", min_value=10, max_value=200, value=50, step=10)

        st.divider()
        st.caption(
            f"Local time: {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')}"
        )

    if uploaded is None:
        st.info("Upload your Spotify streaming history export to get started.")
        return

    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    end_dt = None
    if end_date_enabled and end_date is not None:
        end_dt = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc)

    with st.spinner("Loading and aggregating streaming history…"):
        history = _load_history_from_uploaded(uploaded)
        top_tracks, top_artists, top_albums = aggregates_between(history, start_dt, end_dt)

    if history.empty:
        st.error("Could not parse any plays from that file. Make sure it’s the Spotify streaming history export.")
        return

    filtered = history[history["ts"] >= start_dt].copy()
    if end_dt is not None:
        filtered = filtered[filtered["ts"] < end_dt].copy()

    total_minutes = round(float(filtered["ms_played"].sum()) / 60000.0, 2) if not filtered.empty else 0.0
    st.caption(
        f"Showing plays from {start_dt.date().isoformat()} (UTC)"
        + (f" to {end_dt.date().isoformat()} (exclusive)" if end_dt else "")
        + f". Rows parsed: {len(history):,}. Rows in range: {len(filtered):,}. Minutes: {total_minutes:,.2f}"
    )

    if view == "Tracks":
        df = top_tracks.head(limit)
        st.subheader("Top tracks")
        st.dataframe(df[["rank", "track", "artist", "album", "minutes"]], use_container_width=True, hide_index=True)
        _bar_chart(df, label_col="track", value_col="minutes", title="Minutes listened (top tracks)")

    elif view == "Artists":
        df = top_artists.head(limit)
        st.subheader("Top artists")
        st.dataframe(df[["rank", "artist", "minutes"]], use_container_width=True, hide_index=True)
        _bar_chart(df, label_col="artist", value_col="minutes", title="Minutes listened (top artists)")

    else:
        df = top_albums.head(limit)
        st.subheader("Top albums")
        st.dataframe(df[["rank", "album", "artist", "minutes"]], use_container_width=True, hide_index=True)
        _bar_chart(df, label_col="album", value_col="minutes", title="Minutes listened (top albums)")


if __name__ == "__main__":
    main()

