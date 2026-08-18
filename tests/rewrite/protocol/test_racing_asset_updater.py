from sports_ticker.providers.racing_asset_updater import RacingAssetUpdater

def test_racing_asset_updater_initialization():
    updater = RacingAssetUpdater()
    assert updater is not None
    assert updater._imsa_cache == {}
    assert updater._wec_cache == {}
