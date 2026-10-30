import Foundation

/// The display edits of the Home, Modes, and Teams screens.
extension TickerStore {
    static let utilityModes = ["stock", "weather", "clock", "music", "flights", "airports"]

    /// The mode tile that is selected. Flights covers the tracked flight and the airport board.
    var modeCategory: String {
        let mode = ["flights", "airports"].contains(settings.mode) ? "flights" : settings.mode
        return Self.utilityModes.contains(mode) ? mode : "sports"
    }

    var stockLists: [League] { leagues.filter(\.isStockList) }

    /// The leagues of the My Teams screen: enabled sports leagues that support My Teams.
    var teamLeagues: [League] {
        leagues.filter { $0.isSport && $0.myTeamsEnabled != false && settings.activeSports[$0.id] != false }
    }

    func isEnabled(_ league: League) -> Bool { settings.activeSports[league.id] ?? true }

    func setFilter(_ filter: String) {
        settings.sportsFilter = filter
        beginBurst()
        save()
    }

    /// Select a mode tile. A schedule override keeps the choice until the next scheduled change.
    func setCategory(_ category: String) {
        if isSportsOnly && category != "sports" { return }
        if category != "sports" { unpin() }
        switch category {
        case "flights":
            if !["flights", "airports"].contains(settings.mode) { settings.mode = "airports" }
        case "stock", "weather", "clock", "music":
            settings.mode = category
        default:
            settings.mode = "sports"
        }
        if category == "stock", !stockLists.contains(where: { settings.activeSports[$0.id] == true }), let first = stockLists.first {
            settings.activeSports[first.id] = true
        }
        if category == "music" { Task { await refreshSpotify() } }
        beginBurst()
        save(scheduleOverride: true)
    }

    /// Choose the airport board or the tracked flight of Flights mode.
    func setFlightView(tracking: Bool) {
        settings.mode = tracking ? "flights" : "airports"
        beginBurst()
        save(scheduleOverride: true)
    }

    /// Set the airport of the board. The code is an IATA or an ICAO code.
    func setAirport(_ code: String) {
        let code = code.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard (3...4).contains(code.count) else { return }
        isEditing = true
        settings.airportCodeIATA = code
        save()
    }

    func setTrackedFlight(_ number: String) {
        let flight = number.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard flight != settings.trackFlightID else { return }
        isEditing = true
        settings.trackFlightID = flight
        if flight.isEmpty { settings.trackGuestName = "" }
        save()
    }

    func setGuestName(_ name: String) {
        let guest = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard guest != settings.trackGuestName else { return }
        isEditing = true
        settings.trackGuestName = guest
        save()
    }

    func clearTrackedFlight() {
        isEditing = true
        settings.trackFlightID = ""
        settings.trackGuestName = ""
        save()
    }

    func toggleLeague(_ league: League) {
        settings.activeSports[league.id] = !isEnabled(league)
        save()
    }

    /// Show one stock list. The lists are exclusive.
    func selectStockList(_ id: String) {
        for list in stockLists { settings.activeSports[list.id] = false }
        settings.activeSports[id] = true
        save()
    }

    /// The custom stock list edits the settings of one ticker, so the settings must belong to the active ticker.
    var canEditCustomStocks: Bool { activeTickerID != nil && settingsTickerID == activeTickerID }

    func saveCustomStocks(_ symbols: [String], for tickerID: String?) {
        guard tickerID == activeTickerID, settingsTickerID == tickerID else { return }
        settings.customStockSymbols = symbols
        for list in stockLists { settings.activeSports[list.id] = false }
        // An empty custom list falls back to the Tech / AI list.
        settings.activeSports[symbols.isEmpty ? "stock_tech_ai" : "stock_custom"] = true
        beginBurst()
        save()
    }

    func searchStocks(_ query: String) async throws -> [StockSymbol] {
        try await api.send(API.stocks(query)).stocks
    }

    /// Toggle a team of My Teams. The save waits 1.5 seconds after the last tap.
    func toggleTeam(_ id: String) {
        isEditing = true
        if let index = settings.myTeams.firstIndex(of: id) { settings.myTeams.remove(at: index) } else { settings.myTeams.append(id) }
        session.sharedTeams = settings.myTeams
        beginBurst()
        scheduleTeamSave()
    }

    /// Pin a game, or unpin the pinned game. A pin shows the game across the whole panel in Sports mode.
    func togglePin(_ item: FeedItem) {
        guard item.game != nil else { return }
        if isPinned(item) {
            unpin()
        } else {
            settings.pinnedContentID = item.pinID
            settings.sportsPresentation = "pinned"
            settings.mode = "sports"
        }
        beginBurst()
        save()
    }

    private func unpin() {
        settings.pinnedContentID = ""
        settings.sportsPresentation = "rotation"
    }

    /// Find a city or a postal code, then show its weather.
    func setWeatherLocation(_ query: String) async {
        weatherInput = query
        guard scope() != nil else {
            operationError = "Pair a ticker before changing its weather location."
            return
        }
        let tickerID = activeTickerID
        isEditing = true
        do {
            let place = try await platform.geocode(query)
            guard tickerID == activeTickerID else { return }
            settings.weatherCity = place.name
            settings.weatherLat = place.latitude
            settings.weatherLon = place.longitude
            save()
        } catch {
            guard tickerID == activeTickerID else { return }
            isEditing = false
            operationError = "That weather location could not be found. Check its city or ZIP code."
        }
    }
}
