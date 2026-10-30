import Foundation

/// The display settings of one ticker. The fields follow `DisplaySettings` in `ticker/shared/domain/models.py`.
nonisolated struct DisplaySettings: Codable, Equatable {
    var activeSports: [String: Bool] = [:]
    var myTeams: [String] = []
    var mode = "sports"
    var sportsFilter = "all"
    var sportsPresentation = "rotation"
    var pinnedContentID = ""
    var brightness = 100.0
    var inverted = false
    var timezone = ""
    var weatherCity = "New York"
    var weatherLat = 40.7128
    var weatherLon = -74.0060
    var airportCodeIATA = "EWR"
    var airportCodeICAO = "KEWR"
    var airportName = "Newark Liberty International"
    var trackFlightID = ""
    var trackGuestName = ""
    var liveDelayMode = false
    var liveDelaySeconds = 45.0
    var scrollSeamless = true
    var scrollSpeed = 0.03
    var scoreAlerts = true
    var customStockSymbols: [String] = []

    enum CodingKeys: String, CodingKey {
        case activeSports = "active_sports", myTeams = "my_teams", mode, sportsFilter = "sports_filter"
        case sportsPresentation = "sports_presentation", pinnedContentID = "pinned_content_id", brightness, inverted, timezone
        case weatherCity = "weather_city", weatherLat = "weather_lat", weatherLon = "weather_lon"
        case airportCodeIATA = "airport_code_iata", airportCodeICAO = "airport_code_icao", airportName = "airport_name"
        case trackFlightID = "track_flight_id", trackGuestName = "track_guest_name"
        case liveDelayMode = "live_delay_mode", liveDelaySeconds = "live_delay_seconds"
        case scrollSeamless = "scroll_seamless", scrollSpeed = "scroll_speed", scoreAlerts = "score_alerts"
        case customStockSymbols = "custom_stock_symbols"
    }

    init() {}

    /// A field that the server leaves out keeps the server default.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let defaults = DisplaySettings()
        func read<T: Decodable>(_ key: CodingKeys, _ fallback: T) -> T { (try? c.decodeIfPresent(T.self, forKey: key)) ?? fallback }
        activeSports = read(.activeSports, defaults.activeSports)
        myTeams = read(.myTeams, defaults.myTeams)
        mode = read(.mode, defaults.mode)
        sportsFilter = read(.sportsFilter, defaults.sportsFilter)
        sportsPresentation = read(.sportsPresentation, defaults.sportsPresentation)
        pinnedContentID = read(.pinnedContentID, defaults.pinnedContentID)
        brightness = read(.brightness, defaults.brightness)
        inverted = read(.inverted, defaults.inverted)
        timezone = read(.timezone, defaults.timezone)
        weatherCity = read(.weatherCity, defaults.weatherCity)
        weatherLat = read(.weatherLat, defaults.weatherLat)
        weatherLon = read(.weatherLon, defaults.weatherLon)
        airportCodeIATA = read(.airportCodeIATA, defaults.airportCodeIATA)
        airportCodeICAO = read(.airportCodeICAO, defaults.airportCodeICAO)
        airportName = read(.airportName, defaults.airportName)
        trackFlightID = read(.trackFlightID, defaults.trackFlightID)
        trackGuestName = read(.trackGuestName, defaults.trackGuestName)
        liveDelayMode = read(.liveDelayMode, defaults.liveDelayMode)
        liveDelaySeconds = read(.liveDelaySeconds, defaults.liveDelaySeconds)
        scrollSeamless = read(.scrollSeamless, defaults.scrollSeamless)
        scrollSpeed = read(.scrollSpeed, defaults.scrollSpeed)
        scoreAlerts = read(.scoreAlerts, defaults.scoreAlerts)
        customStockSymbols = read(.customStockSymbols, defaults.customStockSymbols)
    }

    var isPinned: Bool { sportsPresentation == "pinned" && !pinnedContentID.isEmpty }
}

/// A partial settings change. Only the fields that are set go to the server.
nonisolated struct DisplaySettingsPatch: Encodable, Equatable {
    var activeSports: [String: Bool]?
    var myTeams: [String]?
    var mode: String?
    var sportsFilter: String?
    var sportsPresentation: String?
    var pinnedContentID: String?
    var brightness: Double?
    var inverted: Bool?
    var timezone: String?
    var weatherCity: String?
    var weatherLat: Double?
    var weatherLon: Double?
    var airportCodeIATA: String?
    var trackFlightID: String?
    var trackGuestName: String?
    var liveDelayMode: Bool?
    var liveDelaySeconds: Double?
    var scrollSeamless: Bool?
    var scrollSpeed: Double?
    var customStockSymbols: [String]?

    enum CodingKeys: String, CodingKey {
        case activeSports = "active_sports", myTeams = "my_teams", mode, sportsFilter = "sports_filter"
        case sportsPresentation = "sports_presentation", pinnedContentID = "pinned_content_id", brightness, inverted, timezone
        case weatherCity = "weather_city", weatherLat = "weather_lat", weatherLon = "weather_lon"
        case airportCodeIATA = "airport_code_iata", trackFlightID = "track_flight_id", trackGuestName = "track_guest_name"
        case liveDelayMode = "live_delay_mode", liveDelaySeconds = "live_delay_seconds"
        case scrollSeamless = "scroll_seamless", scrollSpeed = "scroll_speed", customStockSymbols = "custom_stock_symbols"
    }

    /// The settings that the app edits on the display screens.
    static func display(_ settings: DisplaySettings, timezone: String) -> DisplaySettingsPatch {
        DisplaySettingsPatch(
            activeSports: settings.activeSports, myTeams: settings.myTeams, mode: settings.mode,
            sportsFilter: settings.sportsFilter, sportsPresentation: settings.isPinned ? "pinned" : "rotation",
            pinnedContentID: settings.isPinned ? settings.pinnedContentID : "", timezone: timezone,
            weatherCity: settings.weatherCity, weatherLat: settings.weatherLat, weatherLon: settings.weatherLon,
            airportCodeIATA: settings.airportCodeIATA, trackFlightID: settings.trackFlightID,
            trackGuestName: settings.trackGuestName, customStockSymbols: settings.customStockSymbols)
    }
}

/// A `PATCH /tickers/<id>` body.
nonisolated struct TickerChange: Encodable, Equatable {
    var name: String?
    var displaySettings: DisplaySettingsPatch?
    var scheduleOverride: Bool?

    enum CodingKeys: String, CodingKey {
        case name, displaySettings = "display_settings", scheduleOverride = "schedule_override"
    }
}
