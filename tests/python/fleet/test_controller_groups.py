from sports_ticker.fleet import SpotifyConnection, TickerRepository


def test_group_spotify_connection_is_shared_without_ticker_credentials(tmp_path) -> None:
    """Keep one encrypted Spotify record under the controller group owner."""

    repository = TickerRepository(tmp_path / "ticker.sqlite3")
    try:
        connection = SpotifyConnection(
            ticker_id="cg_shared",
            spotify_account_id="spotify-user",
            display_name="Test User",
            scopes=("user-read-playback-state",),
            refresh_token_ciphertext="encrypted-refresh-token",
        )
        repository.save_group_spotify_connection("cg_shared", connection)

        records = repository.list_group_spotify_connections("cg_shared")

        assert len(records) == 1
        assert records[0].ticker_id == "cg_shared"
        assert records[0].spotify_account_id == "spotify-user"
        assert records[0].refresh_token_ciphertext == "encrypted-refresh-token"
    finally:
        repository.close()
