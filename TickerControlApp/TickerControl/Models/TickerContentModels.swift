import Foundation

struct LeagueOption: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let label: String
    let type: String
    let enabled: Bool?
    let my_teams_enabled: Bool?
}
struct V2LeagueCatalog: Decodable, Sendable { let leagues: [LeagueOption] }
struct V2TeamCatalog: Decodable, Sendable { let teams: [TeamData] }
struct ModeOption: Decodable, Sendable { let id: String; let symbol: String }
struct V2ModeCatalog: Decodable, Sendable { let modes: [ModeOption] }

struct ShootoutData: Decodable, Hashable, Sendable {
    let away: [String]?
    let home: [String]?
}
struct AirportWeather: Decodable, Hashable, Sendable {
    let iata: String?
    let city: String?
    let away_abbr: String?
    let status: String?
}
struct AirportFlight: Decodable, Hashable, Sendable {
    let away_abbr: String?
    let home_abbr: String?
    let other_iata: String?
    let altitude: String?
}
struct WeatherForecast: Decodable, Hashable, Sendable {
    let day: String?
    let icon: String?
    let high: String?
    let low: String?
    let pop: String?

    enum CodingKeys: String, CodingKey { case day, icon, high, low, pop }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        day = try? c.decode(String.self, forKey: .day)
        icon = try? c.decode(String.self, forKey: .icon)
        high = Self.text(c, key: .high)
        low = Self.text(c, key: .low)
        pop = Self.text(c, key: .pop)
    }

    private static func text(
        _ container: KeyedDecodingContainer<CodingKeys>, key: CodingKeys
    ) -> String? {
        if let value = try? container.decode(String.self, forKey: key) { return value }
        if let value = try? container.decode(Int.self, forKey: key) { return String(value) }
        if let value = try? container.decode(Double.self, forKey: key) { return String(format: "%.0f", value) }
        return nil
    }
}
struct Situation: Decodable, Hashable, Sendable {
    let activeTeam: String?
    let downDist: String?
    let isRedZone: Bool?
    let balls: Int?
    let strikes: Int?
    let outs: Int?
    let onFirst: Bool?
    let onSecond: Bool?
    let onThird: Bool?
    let powerPlay: Bool?
    let emptyNet: Bool?
    let icon: String?
    let change: String?
    let shootout: ShootoutData?

    enum CodingKeys: String, CodingKey {
        case activeTeam, downDist, isRedZone, balls, strikes, outs, onFirst, onSecond, onThird, powerPlay, emptyNet, icon, change, shootout
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        activeTeam = try? container.decode(String.self, forKey: .activeTeam)
        downDist = try? container.decode(String.self, forKey: .downDist)
        isRedZone = try? container.decode(Bool.self, forKey: .isRedZone)
        balls = try? container.decode(Int.self, forKey: .balls)
        strikes = try? container.decode(Int.self, forKey: .strikes)
        outs = try? container.decode(Int.self, forKey: .outs)
        onFirst = try? container.decode(Bool.self, forKey: .onFirst)
        onSecond = try? container.decode(Bool.self, forKey: .onSecond)
        onThird = try? container.decode(Bool.self, forKey: .onThird)
        powerPlay = try? container.decode(Bool.self, forKey: .powerPlay)
        emptyNet = try? container.decode(Bool.self, forKey: .emptyNet)
        icon = try? container.decode(String.self, forKey: .icon)
        change = try? container.decode(String.self, forKey: .change)
        shootout = try? container.decode(ShootoutData.self, forKey: .shootout)
    }
}
struct Game: Identifiable, Decodable, Hashable, Sendable {
    let id: String
    let sport: String
    let status: String
    let state: String?
    let home_abbr: String?
    let home_id: String?
    let home_score: String
    let home_logo: String?
    let home_color: String?
    let home_alt_color: String?
    let away_abbr: String?
    let away_id: String?
    let away_score: String
    let away_logo: String?
    let away_color: String?
    let away_alt_color: String?
    let is_shown: Bool
    let situation: Situation?
    let type: String?
    let tourney_name: String?
    // Flight tracking fields
    let guest_name: String?
    let route: String?
    let origin_city: String?
    let dest_city: String?
    let alt: Int?
    let dist: Int?
    let eta_str: String?
    let speed: Int?
    let progress: Int?
    let is_live: Bool?
    let delay_min: Int?
    let is_delayed: Bool?
    let name: String?
    let artist: String?
    let cover: String?
    let duration: Double?
    let feels: String?
    let wind: String?
    let humidity: String?
    let airportWeather: AirportWeather?
    let arrivals: [AirportFlight]?
    let departures: [AirportFlight]?
    let forecast: [WeatherForecast]?

    var safeHomeAbbr: String { home_abbr ?? "" }
    var safeAwayAbbr: String { away_abbr ?? "" }
    var safeHomeLogo: String { home_logo ?? "" }
    var safeAwayLogo: String { away_logo ?? "" }
    var safeHomeID: String { home_id ?? safeHomeAbbr }
    var safeAwayID: String { away_id ?? safeAwayAbbr }

    enum CodingKeys: String, CodingKey {
        case id, sport, status, state, home_abbr, home_id, home_score, home_logo, home_color, home_alt_color, away_abbr, away_id, away_score, away_logo, away_color, away_alt_color, is_shown, situation, type, tourney_name, guest_name, route, origin_city, dest_city, alt, dist, eta_str, speed, progress, is_live, delay_min, is_delayed, name, artist, cover, duration, feels, wind, humidity, airportWeather = "weather", arrivals, departures, forecast
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        sport = try c.decode(String.self, forKey: .sport)
        status = try c.decode(String.self, forKey: .status)
        state = try? c.decode(String.self, forKey: .state)
        home_abbr = try? c.decode(String.self, forKey: .home_abbr)
        home_logo = try? c.decode(String.self, forKey: .home_logo)
        home_color = try? c.decode(String.self, forKey: .home_color)
        home_alt_color = try? c.decode(String.self, forKey: .home_alt_color)
        away_abbr = try? c.decode(String.self, forKey: .away_abbr)
        away_logo = try? c.decode(String.self, forKey: .away_logo)
        away_color = try? c.decode(String.self, forKey: .away_color)
        away_alt_color = try? c.decode(String.self, forKey: .away_alt_color)
        is_shown = try c.decode(Bool.self, forKey: .is_shown)
        situation = try? c.decode(Situation.self, forKey: .situation)
        type = try? c.decode(String.self, forKey: .type)
        tourney_name = try? c.decode(String.self, forKey: .tourney_name)
        // Flight fields
        guest_name = try? c.decode(String.self, forKey: .guest_name)
        route = try? c.decode(String.self, forKey: .route)
        origin_city = try? c.decode(String.self, forKey: .origin_city)
        dest_city = try? c.decode(String.self, forKey: .dest_city)
        alt = try? c.decode(Int.self, forKey: .alt)
        dist = try? c.decode(Int.self, forKey: .dist)
        eta_str = try? c.decode(String.self, forKey: .eta_str)
        is_live = try? c.decode(Bool.self, forKey: .is_live)
        is_delayed = try? c.decode(Bool.self, forKey: .is_delayed)
        name = try? c.decode(String.self, forKey: .name)
        artist = try? c.decode(String.self, forKey: .artist)
        cover = try? c.decode(String.self, forKey: .cover)
        duration = try? c.decode(Double.self, forKey: .duration)
        feels = Self.text(c, key: .feels)
        wind = Self.text(c, key: .wind)
        humidity = Self.text(c, key: .humidity)
        airportWeather = try? c.decode(AirportWeather.self, forKey: .airportWeather)
        arrivals = try? c.decode([AirportFlight].self, forKey: .arrivals)
        departures = try? c.decode([AirportFlight].self, forKey: .departures)
        forecast = try? c.decode([WeatherForecast].self, forKey: .forecast)
        if let dmin = try? c.decode(Int.self, forKey: .delay_min) { delay_min = dmin }
        else if let dminD = try? c.decode(Double.self, forKey: .delay_min) { delay_min = Int(dminD) }
        else { delay_min = nil }
        if let spd = try? c.decode(Int.self, forKey: .speed) { speed = spd }
        else if let spdD = try? c.decode(Double.self, forKey: .speed) { speed = Int(spdD) }
        else { speed = nil }
        if let prog = try? c.decode(Int.self, forKey: .progress) { progress = prog }
        else if let progD = try? c.decode(Double.self, forKey: .progress) { progress = Int(progD) }
        else { progress = nil }

        if let hid = try? c.decode(String.self, forKey: .home_id) { home_id = hid }
        else if let hidInt = try? c.decode(Int.self, forKey: .home_id) { home_id = String(hidInt) }
        else { home_id = nil }

        if let aid = try? c.decode(String.self, forKey: .away_id) { away_id = aid }
        else if let aidInt = try? c.decode(Int.self, forKey: .away_id) { away_id = String(aidInt) }
        else { away_id = nil }

        if let hs = try? c.decode(String.self, forKey: .home_score) { home_score = hs }
        else if let hsInt = try? c.decode(Int.self, forKey: .home_score) { home_score = String(hsInt) }
        else { home_score = "0" }

        if let `as` = try? c.decode(String.self, forKey: .away_score) { away_score = `as` }
        else if let asInt = try? c.decode(Int.self, forKey: .away_score) { away_score = String(asInt) }
        else { away_score = "0" }
    }

    private static func text(
        _ container: KeyedDecodingContainer<CodingKeys>, key: CodingKeys
    ) -> String? {
        if let value = try? container.decode(String.self, forKey: key) { return value }
        if let value = try? container.decode(Int.self, forKey: key) { return String(value) }
        if let value = try? container.decode(Double.self, forKey: key) { return String(format: "%.0f", value) }
        return nil
    }
}
struct TeamData: Decodable, Identifiable, Hashable, Sendable {
    let id: String // Proper Smart ID (e.g. nfl:NYG)
    let abbr: String
    let logo: String?
}
struct TickerState: Codable, Sendable {
    var active_sports: [String: Bool]
    var mode: String
    var sports_filter: String
    var scroll_seamless: Bool
    var my_teams: [String]
    var debug_mode: Bool
    var custom_date: String?
    var scroll_speed: Double // Double fixed
    var show_debug_options: Bool
    var weather_location: String
    var weather_city: String
    var weather_lat: Double
    var weather_lon: Double
    var ticker_id: String?
    // Flight tracking
    var track_flight_id: String
    var track_guest_name: String
    var airport_code_iata: String
    var airport_code_icao: String
    var airport_name: String
    var flight_submode: String
    var pinned_game: String?
    var pinned_games: [String]
    var sports_presentation: String
    var pinned_content_id: String
    enum CodingKeys: String, CodingKey {
        case active_sports, mode, sports_filter, scroll_seamless, my_teams, debug_mode, custom_date, scroll_speed, show_debug_options, weather_location, weather_city, weather_lat, weather_lon, ticker_id, track_flight_id, track_guest_name, airport_code_iata, airport_code_icao, airport_name, flight_submode, pinned_game, pinned_games, sports_presentation, pinned_content_id
    }

    // === 1. ROBUST DECODER ===
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        // If server fails to send sports, default to ALL enabled (Safety Net)
        active_sports = (try? container.decode([String: Bool].self, forKey: .active_sports)) ?? TickerState.defaultActiveSports

        let rawMode = (try? container.decode(String.self, forKey: .mode)) ?? "sports"
        if rawMode == "flight2" {
            mode = "flights"
            flight_submode = "track"
        } else {
            mode = rawMode
            flight_submode = (try? container.decode(String.self, forKey: .flight_submode)) ?? "airport"
        }
        sports_filter = (try? container.decode(String.self, forKey: .sports_filter)) ?? "all"
        scroll_seamless = (try? container.decode(Bool.self, forKey: .scroll_seamless)) ?? false
        my_teams = (try? container.decode([String].self, forKey: .my_teams)) ?? []
        debug_mode = (try? container.decode(Bool.self, forKey: .debug_mode)) ?? false
        custom_date = try? container.decodeIfPresent(String.self, forKey: .custom_date)

        // Handle Speed Safety (Double or Int)
        if let speedDouble = try? container.decode(Double.self, forKey: .scroll_speed) {
            scroll_speed = speedDouble
        } else if let speedInt = try? container.decode(Int.self, forKey: .scroll_speed) {
            scroll_speed = Double(speedInt)
        } else {
            scroll_speed = 5.0
        }

        show_debug_options = (try? container.decode(Bool.self, forKey: .show_debug_options)) ?? false
        weather_location = (try? container.decode(String.self, forKey: .weather_location)) ?? "New York"
        weather_city = (try? container.decode(String.self, forKey: .weather_city)) ?? "New York"
        weather_lat = (try? container.decode(Double.self, forKey: .weather_lat)) ?? 40.7128
        weather_lon = (try? container.decode(Double.self, forKey: .weather_lon)) ?? -74.0060
        ticker_id = try? container.decodeIfPresent(String.self, forKey: .ticker_id)
        // Flight tracking
        track_flight_id = (try? container.decode(String.self, forKey: .track_flight_id)) ?? ""
        track_guest_name = (try? container.decode(String.self, forKey: .track_guest_name)) ?? ""
        airport_code_iata = (try? container.decode(String.self, forKey: .airport_code_iata)) ?? "EWR"
        airport_code_icao = (try? container.decode(String.self, forKey: .airport_code_icao)) ?? "KEWR"
        airport_name = (try? container.decode(String.self, forKey: .airport_name)) ?? "Newark"
        pinned_game = try? container.decodeIfPresent(String.self, forKey: .pinned_game)
        let decodedPins = (try? container.decode([String].self, forKey: .pinned_games)) ?? []
        if !decodedPins.isEmpty {
            pinned_games = decodedPins
        } else if let single = pinned_game?.trimmingCharacters(in: .whitespacesAndNewlines), !single.isEmpty {
            pinned_games = [single]
        } else {
            pinned_games = []
        }
        sports_presentation = (try? container.decode(String.self, forKey: .sports_presentation)) ?? "rotation"
        pinned_content_id = (try? container.decode(String.self, forKey: .pinned_content_id)) ?? pinned_games.first ?? ""
    }

    // === 2. BETTER DEFAULTS (Fixes "NFL Only" bug) ===
    init(active_sports: [String: Bool]? = nil, mode: String = "sports", sports_filter: String = "all", scroll_seamless: Bool = false, my_teams: [String] = [], debug_mode: Bool = false, custom_date: String? = nil, scroll_speed: Double = 5.0, show_debug_options: Bool = false, weather_location: String = "New York", weather_city: String = "New York", weather_lat: Double = 40.7128, weather_lon: Double = -74.0060, ticker_id: String? = nil, track_flight_id: String = "", track_guest_name: String = "", airport_code_iata: String = "EWR", airport_code_icao: String = "KEWR", airport_name: String = "Newark", flight_submode: String = "airport", pinned_game: String? = nil, pinned_games: [String] = [], sports_presentation: String = "rotation", pinned_content_id: String = "") {

        // Default to ALL sports if none provided
        self.active_sports = active_sports ?? TickerState.defaultActiveSports

        self.mode = mode
        self.sports_filter = sports_filter
        self.scroll_seamless = scroll_seamless
        self.my_teams = my_teams
        self.debug_mode = debug_mode
        self.custom_date = custom_date
        self.scroll_speed = scroll_speed
        self.show_debug_options = show_debug_options
        self.weather_location = weather_location
        self.weather_city = weather_city
        self.weather_lat = weather_lat
        self.weather_lon = weather_lon
        self.ticker_id = ticker_id
        self.track_flight_id = track_flight_id
        self.track_guest_name = track_guest_name
        self.airport_code_iata = airport_code_iata
        self.airport_code_icao = airport_code_icao
        self.airport_name = airport_name
        self.flight_submode = flight_submode
        self.pinned_game = pinned_game
        self.pinned_games = pinned_games
        self.sports_presentation = sports_presentation
        self.pinned_content_id = pinned_content_id
    }
    // Empty values use the server defaults for every league.
    static var defaultActiveSports: [String: Bool] { [:] }
}
struct V2DataResponse: Decodable, Sendable {
    let settings: TickerState
    let content: [String: [V2ContentItem]]
    let meta: V2DataMeta

    var games: [Game] {
        let preferredFamilies = ["sports", "golf", "racing", "weather", "music", "flights", "airports", "clock", "status", "stock"]
        let orderedFamilies = preferredFamilies.filter(content.keys.contains) + content.keys.filter { !preferredFamilies.contains($0) }.sorted()
        return orderedFamilies.flatMap { content[$0, default: []] }
            .compactMap(Game.init(content:))
            .filter { $0.type != "fan_duel_joke_ad" }
    }
}
struct V2DataMeta: Decodable, Sendable {
    let pairing: V2PairingMeta?
    let schedule: TickerScheduleStatus?
}
struct V2PairingMeta: Decodable, Sendable { let paired: Bool; let code: String? }
struct JSONValue: Codable, Sendable {
    let value: AnySendableValue

    nonisolated init(value: AnySendableValue) {
        self.value = value
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { value = .null }
        else if let value = try? container.decode(Bool.self) { self.value = .bool(value) }
        else if let value = try? container.decode(Double.self) { self.value = .number(value) }
        else if let value = try? container.decode(String.self) { self.value = .string(value) }
        else if let value = try? container.decode([String: JSONValue].self) { self.value = .object(value) }
        else if let value = try? container.decode([JSONValue].self) { self.value = .array(value) }
        else { throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON value") }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case .null: try container.encodeNil()
        case .bool(let item): try container.encode(item)
        case .number(let item): try container.encode(item)
        case .string(let item): try container.encode(item)
        case .object(let item): try container.encode(item)
        case .array(let item): try container.encode(item)
        }
    }
}

enum AnySendableValue: Sendable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case object([String: JSONValue])
    case array([JSONValue])
}

struct V2ContentItem: Decodable, Sendable {
    let id: String
    let family: String
    let kind: String
    let is_shown: Bool
    let data: [String: JSONValue]
}

extension Game {
    nonisolated init?(content: V2ContentItem) {
        var payload = content.data
        payload["id"] = JSONValue(value: .string(content.id))
        payload["sport"] = payload["sport"] ?? JSONValue(value: .string(content.family))
        payload["status"] = payload["status"] ?? JSONValue(value: .string(""))
        payload["type"] = payload["type"] ?? JSONValue(value: .string(content.kind))
        payload["is_shown"] = JSONValue(value: .bool(content.is_shown))
        guard let encoded = try? JSONEncoder().encode(payload) else { return nil }
        guard let game = try? JSONDecoder().decode(Game.self, from: encoded) else { return nil }
        self = game
    }
}

struct DeviceSettings: Sendable {
    var brightness: Double
    var scroll_speed: Double
    var scroll_seamless: Bool?
    var inverted: Bool?
    var live_delay_mode: Bool?
    var live_delay_seconds: Int?
}

struct V2Ticker: Decodable, Sendable {
    let ticker_id: String
    let id: String
    let name: String
    let display_settings: V2DisplaySettings
    let device: V2Device
    let profile: TickerProfile?

    enum CodingKeys: String, CodingKey { case ticker_id, name, display_settings, device, profile }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        ticker_id = try container.decode(String.self, forKey: .ticker_id)
        id = ticker_id
        name = try container.decode(String.self, forKey: .name)
        display_settings = try container.decode(V2DisplaySettings.self, forKey: .display_settings)
        device = try container.decode(V2Device.self, forKey: .device)
        profile = try container.decodeIfPresent(TickerProfile.self, forKey: .profile)
    }

    var tickerDevice: TickerDevice {
        TickerDevice(
            id: ticker_id,
            name: name,
            settings: DeviceSettings(
                brightness: display_settings.brightness,
                scroll_speed: display_settings.scroll_speed,
                scroll_seamless: display_settings.scroll_seamless,
                inverted: display_settings.inverted,
                live_delay_mode: display_settings.live_delay_mode,
                live_delay_seconds: Int(display_settings.live_delay_seconds)
            ),
            last_seen: device.last_seen_at,
            capabilities: device.capabilities.isEmpty ? Set(profile?.capabilities.modes.map { $0.lowercased() } ?? []) : device.capabilities,
            profile: profile
        )
    }
}

struct V2TickerList: Decodable, Sendable { let tickers: [V2Ticker] }

struct V2Device: Decodable, Sendable {
    let last_seen_at: Double?
    let metadata: [String: JSONValue]?

    var capabilities: Set<String> {
        guard let value = metadata?["capabilities"], case .array(let values) = value.value else {
            return []
        }
        return Set(values.compactMap { item in
            guard case .string(let capability) = item.value else { return nil }
            return capability.lowercased()
        })
    }
}

struct V2DisplaySettings: Decodable, Sendable {
    let brightness: Double
    let scroll_speed: Double
    let scroll_seamless: Bool?
    let inverted: Bool?
    let live_delay_mode: Bool?
    let live_delay_seconds: Double
}

struct TickerDevice: Identifiable, Sendable {
    let id: String
    let name: String
    var settings: DeviceSettings
    let last_seen: Double?
    let capabilities: Set<String>
    let profile: TickerProfile?
}

struct PairingExchangeResponse: Decodable, Sendable {
    let ticker_id: String?
    let controller_token: String
    let controller_group_id: String?
    let controller_group_secret: String?
}
struct PairingCodeResponse: Decodable, Sendable { let pairing_code: String }

struct SpotifyAuthorization: Decodable, Sendable { let attempt_id: String; let authorization_url: URL }
struct SpotifyAccount: Decodable, Identifiable, Sendable {
    let spotify_account_id: String
    let display_name: String
    let status: String
    let connected: Bool
    let priority: Bool
    var id: String { spotify_account_id }
}
struct SpotifyStatus: Decodable, Sendable {
    let connected: Bool
    let status: String
    let display_name: String?
    let accounts: [SpotifyAccount]
    let priority_account_id: String?
}
// ==========================================
// MARK: - 2. VIEW MODEL
// ==========================================
