import Foundation
import Testing
@testable import TickerControlCore

@MainActor
struct StoreTests {
    /// Let the tasks of the store run until `condition` is true.
    private func settle(_ condition: () -> Bool, sourceLocation: SourceLocation = #_sourceLocation) async {
        for _ in 0..<500 {
            if condition() { return }
            await Task.yield()
        }
        Issue.record("the condition did not become true", sourceLocation: sourceLocation)
    }

    private func settings(_ request: URLRequest, _ server: FakeServer) -> [String: Any] {
        server.body(request)["display_settings"] as? [String: Any] ?? [:]
    }

    @Test func dataReadAppliesSettingsAndSharesTheFirstTeamList() async {
        let h = Harness()
        h.server.on("GET", "/tickers/t1/data", Harness.data(mode: "weather", items: [Harness.game("g1")]))
        await h.store.refreshData()
        #expect(h.store.settings.mode == "weather")
        #expect(h.store.settingsTickerID == "t1")
        #expect(h.store.weatherInput == "Newark")
        #expect(h.values.stringArray(forKey: "sharedMyTeams") == ["nfl:NYG"])
        #expect(h.store.connection == ConnectionStatus(text: "Connected • 1 Items", tone: .good))
        #expect(h.server.requests.first?.value(forHTTPHeaderField: "Authorization") == "Bearer token-t1")
    }

    @Test func readDuringAnEditKeepsTheLocalSettings() async {
        let h = Harness()
        h.values.values["sharedMyTeams"] = ["mlb:NYY"]
        h.server.on("GET", "/tickers/t1/data", Harness.data(mode: "weather", items: [Harness.game("g1")]))
        h.store.isEditing = true
        h.store.settings.mode = "stock"
        await h.store.refreshData()
        #expect(h.store.settings.mode == "stock")
        #expect(h.store.feed.count == 1)
        h.store.isEditing = false
        await h.store.refreshData()
        #expect(h.store.settings.myTeams == ["mlb:NYY"], "My Teams of the app replace the list of one ticker")
    }

    @Test func oneSaveRunsAtATimeAndLaterEditsJoinTheNextSave() async {
        let h = Harness()
        h.server.on("PATCH", "/tickers/t1", Harness.ticker("t1"))
        h.server.on("GET", "/tickers/t1/data", Harness.data(mode: "music"))
        h.server.held = true
        h.store.settings.mode = "stock"
        h.store.save()
        h.store.settings.mode = "music"
        h.store.save(scheduleOverride: true)
        h.store.save()
        await settle { h.server.sent("PATCH", "/tickers/t1").count == 1 }
        h.server.release()
        await settle { h.server.sent("PATCH", "/tickers/t1").count == 2 }
        h.server.release()
        await settle { !h.store.isEditing }
        let patches = h.server.sent("PATCH", "/tickers/t1")
        #expect(patches.count == 2)
        #expect((settings(patches[0], h.server)["mode"] as? String) == "stock")
        #expect(h.server.body(patches[0])["schedule_override"] == nil)
        #expect((settings(patches[1], h.server)["mode"] as? String) == "music")
        #expect((h.server.body(patches[1])["schedule_override"] as? Bool) == true)
        #expect(h.store.operationError == nil)
    }

    @Test func failedSaveReportsTheServerMessage() async {
        let h = Harness()
        h.server.on("PATCH", "/tickers/t1", status: 400, ["error": ["code": "invalid_request", "message": "bad mode"]])
        h.store.save()
        await settle { h.store.operationError != nil }
        #expect(h.store.operationError == "The server rejected the request (HTTP 400). bad mode")
        #expect(!h.store.isEditing)
    }

    @Test func readOfTheReplacedTickerIsIgnored() async {
        let h = Harness(paired: ["t1", "t2"])
        h.server.on("GET", "/tickers", ["tickers": [Harness.ticker("t1"), Harness.ticker("t2")]])
        await h.store.refreshDevices()
        h.server.on("GET", "/tickers/t1/data", Harness.data(mode: "weather"))
        h.server.on("GET", "/tickers/t2/data", Harness.data(mode: "clock"))
        h.server.held = true
        let stale = Task { await h.store.refreshData() }
        await settle { h.server.sent("GET", "/tickers/t1/data").count == 1 }
        h.store.switchTicker("t2")
        h.server.release()
        await stale.value
        await settle { h.store.settings.mode == "clock" }
        #expect(h.store.activeTickerID == "t2")
        #expect(h.values.string(forKey: "latchedTickerID") == "t2")
    }

    @Test func pairingSavesTheTokenSelectsTheTickerAndNamesIt() async {
        let h = Harness(paired: [], active: nil)
        h.server.on("POST", "/pair", status: 201, ["ticker_id": "new", "controller_token": "fresh", "controller_group_id": "g1",
                                                  "controller_group_secret": "s1", "paired": true])
        h.server.on("PATCH", "/tickers/new", Harness.ticker("new"))
        h.server.on("GET", "/tickers", ["tickers": [Harness.ticker("new")]])
        h.server.on("GET", "/tickers/new/data", Harness.data())
        h.server.on("GET", "/tickers/new/spotify", ["connected": false, "status": "none", "accounts": []])
        #expect(h.store.needsSetup)
        let paired = await h.store.pair(code: "123456", name: "Kitchen", shareGroup: true)
        #expect(paired)
        #expect(h.store.activeTickerID == "new")
        #expect(h.store.pairSucceeded)
        #expect(h.store.session.token(for: "new") == "fresh")
        #expect(h.store.session.groupID == "g1")
        #expect(h.store.canShareGroup)
        #expect((h.server.body(h.server.sent("POST", "/pair")[0]) as NSDictionary) == ["pairing_code": "123456"])
        #expect((h.server.body(h.server.sent("PATCH", "/tickers/new")[0]) as NSDictionary) == ["name": "Kitchen"])
        #expect(h.store.devices.map(\.id) == ["new"])
        #expect(h.store.spotify.status == "Not connected")
    }

    @Test func groupPairingSendsTheGroupSecret() async {
        let h = Harness(paired: ["t1"])
        #expect(h.store.session.saveGroup(id: "g1", secret: "s1"))
        h.server.on("POST", "/pair", status: 201, ["ticker_id": "t2", "controller_token": "x", "controller_group_id": "g1"])
        _ = await h.store.pair(code: "654321", name: "Den", shareGroup: true)
        #expect((h.server.body(h.server.sent("POST", "/pair")[0]) as NSDictionary) == ["pairing_code": "654321", "controller_group_id": "g1", "controller_group_secret": "s1"])
    }

    @Test func failedTokenWriteKeepsTheSelection() async {
        let h = Harness(paired: [], active: nil)
        h.credentials.failsWrites = true
        h.server.on("POST", "/pair", status: 201, ["ticker_id": "new", "controller_token": "fresh"])
        let paired = await h.store.pair(code: "123456", name: "Kitchen", shareGroup: false)
        #expect(!paired)
        #expect(h.store.activeTickerID == nil)
        #expect(h.store.pairError == "Pairing failed: the controller token could not be saved securely.")
    }

    @Test func unpairSelectsAnotherPairedTicker() async {
        let h = Harness(paired: ["t1", "t2"])
        h.server.on("GET", "/tickers", ["tickers": [Harness.ticker("t1"), Harness.ticker("t2")]])
        await h.store.refreshDevices()
        h.server.on("DELETE", "/tickers/t1/pairing", ["ticker_id": "t1", "paired": false, "pairing_code": "999999"])
        h.server.on("GET", "/tickers", ["tickers": [Harness.ticker("t2")]])
        h.server.on("GET", "/tickers/t2/data", Harness.data(mode: "clock"))
        await h.store.unpair("t1")
        #expect(h.store.activeTickerID == "t2")
        #expect(h.store.session.token(for: "t1") == nil)
        #expect(h.store.settings.mode == "clock")
        #expect(h.store.pairCodeMessage == "Ticker unpaired. Its new pairing code is 999999.")
    }

    @Test func sportsOnlyTickerReturnsToSportsMode() async {
        let h = Harness()
        h.server.on("GET", "/tickers", ["tickers": [Harness.ticker("t1", modes: ["sports"])]])
        h.server.on("PATCH", "/tickers/t1", Harness.ticker("t1"))
        h.store.settings.mode = "weather"
        await h.store.refreshDevices()
        #expect(h.store.isSportsOnly)
        #expect(h.store.settings.mode == "sports")
        await settle { h.server.sent("PATCH", "/tickers/t1").count == 1 }
        h.store.setCategory("music")
        #expect(h.store.settings.mode == "sports", "a sports-only ticker offers no other mode")
    }

    @Test func pinAndUnpinAGame() async throws {
        let h = Harness()
        h.server.on("GET", "/tickers/t1/data", Harness.data(items: [Harness.game("Game-1"), Harness.game("game-2")]))
        h.server.on("PATCH", "/tickers/t1", Harness.ticker("t1"))
        await h.store.refreshData()
        let item = try #require(h.store.feed.first { $0.id == "Game-1" })
        h.server.on("GET", "/tickers/t1/data", Harness.data(items: [Harness.game("Game-1")],
                                                            settings: ["sports_presentation": "pinned", "pinned_content_id": "game-1"]))
        h.store.togglePin(item)
        #expect(h.store.isPinned(item))
        await settle { h.server.sent("PATCH", "/tickers/t1").count == 1 }
        let pinned = settings(h.server.sent("PATCH", "/tickers/t1")[0], h.server)
        #expect((pinned["pinned_content_id"] as? String) == "game-1")
        #expect((pinned["sports_presentation"] as? String) == "pinned")
        await settle { h.server.sent("GET", "/tickers/t1/data").count == 2 }
        #expect(h.store.isPinned(item), "the read after the save keeps the pin")
        h.store.togglePin(item)
        await settle { h.server.sent("PATCH", "/tickers/t1").count == 2 }
        let unpinned = settings(h.server.sent("PATCH", "/tickers/t1")[1], h.server)
        #expect((unpinned["sports_presentation"] as? String) == "rotation")
        #expect((unpinned["pinned_content_id"] as? String) == "")
    }

    @Test func modeTilesChooseTheModeAndAStockList() async {
        let h = Harness()
        h.server.on("GET", "/leagues", ["leagues": [["id": "stock_tech_ai", "label": "Tech", "type": "stock"],
                                                    ["id": "stock_custom", "label": "Custom", "type": "stock"]]])
        h.server.on("GET", "/modes", ["modes": [["id": "stock", "symbol": "chart.bar"]]])
        h.server.on("PATCH", "/tickers/t1", Harness.ticker("t1"))
        await h.store.loadCatalog()
        #expect(h.store.modeSymbol("stock") == "chart.bar")
        #expect(h.store.modeSymbol("clock") == "clock.fill")
        h.store.setCategory("stock")
        #expect(h.store.settings.mode == "stock")
        #expect(h.store.settings.activeSports["stock_tech_ai"] == true)
        await settle { h.server.sent("PATCH", "/tickers/t1").count == 1 }
        #expect((h.server.body(h.server.sent("PATCH", "/tickers/t1")[0])["schedule_override"] as? Bool) == true)
        h.store.setCategory("flights")
        #expect(h.store.settings.mode == "airports")
        #expect(h.store.modeCategory == "flights")
    }

    @Test func customStocksNeedTheSettingsOfTheActiveTicker() async {
        let h = Harness()
        h.server.on("GET", "/tickers/t1/data", Harness.data(mode: "stock"))
        h.server.on("PATCH", "/tickers/t1", Harness.ticker("t1"))
        #expect(!h.store.canEditCustomStocks)
        h.store.saveCustomStocks(["NVDA"], for: "t1")
        #expect(h.server.sent("PATCH", "/tickers/t1").isEmpty)
        await h.store.refreshData()
        h.store.saveCustomStocks([], for: "t1")
        #expect(h.store.settings.activeSports["stock_tech_ai"] == true, "an empty list falls back to Tech / AI")
        await settle { h.server.sent("PATCH", "/tickers/t1").count == 1 }
    }

    @Test func weatherLocationGeocodesThenSaves() async {
        let h = Harness()
        h.server.on("PATCH", "/tickers/t1", Harness.ticker("t1"))
        await h.store.setWeatherLocation("Boston, MA")
        #expect(h.store.settings.weatherCity == "Boston")
        await settle { h.server.sent("PATCH", "/tickers/t1").count == 1 }
        #expect((settings(h.server.sent("PATCH", "/tickers/t1")[0], h.server)["weather_lat"] as? Double) == 42.36)
        await h.store.setWeatherLocation("nowhere")
        #expect(h.store.operationError == "That weather location could not be found. Check its city or ZIP code.")
    }

    @Test func teamTapsSendOneDebouncedSave() async {
        let h = Harness()
        h.server.on("PATCH", "/tickers/t1", Harness.ticker("t1"))
        h.store.toggleTeam("nfl:NYG")
        h.store.toggleTeam("nfl:DAL")
        h.store.toggleTeam("nfl:NYG")
        #expect(h.values.stringArray(forKey: "sharedMyTeams") == ["nfl:DAL"])
        try? await Task.sleep(nanoseconds: 1_700_000_000)
        await settle { h.server.sent("PATCH", "/tickers/t1").count == 1 }
        #expect((settings(h.server.sent("PATCH", "/tickers/t1")[0], h.server)["my_teams"] as? [String]) == ["nfl:DAL"])
    }

    @Test func spotifySignInReadsTheAccountsAfterTheCallback() async {
        let h = Harness()
        h.server.on("POST", "/tickers/t1/spotify/login", status: 201, ["attempt_id": "a1", "authorization_url": "https://accounts.spotify.com/x"])
        h.server.on("GET", "/tickers/t1/spotify", ["connected": true, "status": "connected", "display_name": "Matt",
            "accounts": [["spotify_account_id": "s1", "display_name": "Matt", "status": "connected", "connected": true, "priority": true]]])
        await h.store.connectSpotify()
        #expect(h.store.spotify.status == "Connected")
        #expect(h.store.spotify.accounts.map(\.id) == ["s1"])
        #expect(!h.store.spotify.connecting)
        await h.store.handleSpotifyCallback(URL(string: "tickercontrol://spotify?attempt_id=a2&status=denied")!)
        #expect(h.store.spotify.error == "Spotify authorization did not complete.")
    }

    @Test func wiFiSetupPairsWithTheReturnedCode() async {
        let h = Harness(paired: [], active: nil)
        h.server.on("POST", "/pair", status: 201, ["ticker_id": "mini", "controller_token": "x"])
        h.store.wifi.code = "12345"
        await h.store.startWiFiSetup()
        #expect(h.store.wifi.error == "Enter the six-digit WIFI PIN shown on the ticker.")
        h.store.wifi.code = "123456"
        await h.store.detectWiFi()
        #expect(h.store.wifi.ssid == "Home")
        await h.store.startWiFiSetup()
        #expect(h.store.wifi.status == "Wi-Fi saved. Ticker paired successfully.")
        #expect(h.store.activeTickerID == "mini")
        #expect(!h.store.wifi.inProgress)
    }

    @Test func scheduleOverrideReadsTheNewEffectiveState() async throws {
        let h = Harness()
        h.server.on("PATCH", "/tickers/t1", Harness.ticker("t1"))
        h.server.on("GET", "/tickers/t1/data", Harness.data())
        h.server.on("GET", "/tickers/t1/schedule", ["timezone": "America/New_York", "blocks": [], "conditions": [], "live_games": 0,
                                                     "effective": ["has_enabled_rules": true, "override": true]])
        try await h.store.setScheduleOverride(true)
        #expect(h.store.schedule?.override == true)
        #expect((h.server.body(h.server.sent("PATCH", "/tickers/t1")[0]) as NSDictionary) == ["schedule_override": true])
    }

    @Test func unpairedStoreAsksForPairing() async {
        let h = Harness(paired: [], active: nil)
        await h.store.refreshData()
        #expect(h.store.connection == ConnectionStatus(text: "Pair a ticker to connect", tone: .warning))
        h.store.save()
        #expect(h.store.operationError == "Pair this ticker before changing its settings.")
        #expect(h.server.requests.isEmpty)
    }
}
