import SwiftUI
import Foundation
import Combine
import UIKit
import CoreLocation
import Security
import AuthenticationServices
// ==========================================
// MARK: - 0. EXTENSIONS
// ==========================================
extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 3: (a, r, g, b) = (255, (int >> 8) * 17, (int >> 4 & 0xF) * 17, (int & 0xF) * 17)
        case 6: (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8: (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default: (a, r, g, b) = (1, 1, 1, 0)
        }
        self.init(.sRGB, red: Double(r) / 255, green: Double(g) / 255, blue:  Double(b) / 255, opacity: Double(a) / 255)
    }
    
    var isGrayscaleOrBlack: Bool {
        guard let components = self.cgColor?.components, components.count >= 3 else { return true }
        let r = components[0], g = components[1], b = components[2]
        let maxC = max(r, max(g, b))
        let delta = maxC - min(r, min(g, b))
        let saturation = maxC == 0 ? 0 : delta / maxC
        let brightness = (r * 0.299) + (g * 0.587) + (b * 0.114)
        return brightness < 0.1 || saturation < 0.15
    }
}
// Global helper visible to all views
func prioritizeVibrantColor(primary: String?, alternate: String?) -> Color {
    let pColor = Color(hex: primary ?? "#000000")
    let aColor = Color(hex: alternate ?? "#000000")
    if pColor.isGrayscaleOrBlack && !aColor.isGrayscaleOrBlack { return aColor }
    return pColor
}
// ==========================================
// MARK: - 1. DATA MODELS
// ==========================================
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
        return orderedFamilies.flatMap { content[$0, default: []] }.compactMap(Game.init(content:))
    }
}
struct V2DataMeta: Decodable, Sendable { let pairing: V2PairingMeta? }
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

    enum CodingKeys: String, CodingKey { case ticker_id, name, display_settings, device }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        ticker_id = try container.decode(String.self, forKey: .ticker_id)
        id = ticker_id
        name = try container.decode(String.self, forKey: .name)
        display_settings = try container.decode(V2DisplaySettings.self, forKey: .display_settings)
        device = try container.decode(V2Device.self, forKey: .device)
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
            capabilities: device.capabilities
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
}
struct PairingExchangeResponse: Decodable, Sendable {
    let ticker_id: String?
    let controller_token: String
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
@MainActor
class TickerViewModel: NSObject, ObservableObject, ASWebAuthenticationPresentationContextProviding {
    @Published var games: [Game] = []
    @Published var allTeams: [String: [TeamData]] = [:]
    @Published var leagueOptions: [LeagueOption] = []
    @Published var modeSymbols: [String: String] = [:]
    var leagueLabels: [String: String] { Dictionary(uniqueKeysWithValues: leagueOptions.map { ($0.id, $0.label) }) }
    var isSportsMode: Bool {
        !["stock", "weather", "clock", "music", "flights", "airports"].contains(state.mode)
    }
    var isSportsOnly: Bool {
        guard let activeID = savedTickerID,
              let capabilities = devices.first(where: { $0.id == activeID })?.capabilities else { return false }
        return capabilities == Set(["sports"])
    }
    
    // THE SOURCE OF TRUTH
    @Published var state: TickerState = TickerState(
            active_sports: nil, // This will now trigger the "All Sports" default
            mode: "sports",
            scroll_seamless: false,
            my_teams: [],
            debug_mode: false,
            custom_date: nil,
            scroll_speed: 0.03,
            weather_location: "New York",
            weather_city: "New York",
            weather_lat: 40.7128,
            weather_lon: -74.0060
        )
    
    @Published var pinnedGameIDs: [String] = []
    @Published var devices: [TickerDevice] = []
    @Published var pairCode: String = ""
    @Published var pairName: String = ""
    @Published var pairID: String = ""
    @Published var pairError: String?
    @Published var showPairSuccess: Bool = false
    @Published var serverURL: String { didSet { UserDefaults.standard.set(serverURL, forKey: "serverURL") } }
    @Published var weatherLocInput: String = "New York"
    @Published var connectionStatus: String = "Connecting..."
    @Published var statusColor: Color = .gray
    @Published var spotifyStatus: String = "Checking Spotify..."
    @Published var spotifyAccountName: String?
    @Published var spotifyAccounts: [SpotifyAccount] = []
    @Published var spotifyError: String?
    @Published var isConnectingSpotify = false
    @Published var pairCodeAlertMessage = ""
    @Published var showingPairCodeAlert = false
    
    // LOCKING MECHANISM (Stops updates while you tap)
    @Published var isEditing: Bool = false
    
    private var isServerReachable = false
    private var timer: Timer?
    private var devicesTimer: Timer?
    private var saveDebounceTimer: Timer?
    private var currentSaveTask: URLSessionDataTask?
    private var spotifyAuthorizationSession: ASWebAuthenticationSession?
    private var lastFetchTime: Date = .distantPast
    // After a mode switch, poll every 1s for 30s so the UI and hardware
    // board confirm the new state almost immediately.
    private var burstPollUntil: Date = .distantPast
    private func normalizedPin(_ raw: String) -> String {
        raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
    func pinID(for game: Game) -> String {
        normalizedPin(game.id)
    }
    func isPinned(_ game: Game) -> Bool {
        pinnedGameIDs.contains(pinID(for: game))
    }
    
    // PERSISTENT ID TRACKING
    // Remembers your ticker ID so the app doesn't accidentally load empty globals
    private var savedTickerID: String? {
        get { UserDefaults.standard.string(forKey: "latchedTickerID") }
        set { UserDefaults.standard.set(newValue, forKey: "latchedTickerID") }
    }

    private func controllerToken(for tickerID: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "matt.TickerControl.controller-token",
            kSecAttrAccount as String: tickerID,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func saveControllerToken(_ token: String, for tickerID: String) {
        removeControllerToken(for: tickerID)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "matt.TickerControl.controller-token",
            kSecAttrAccount as String: tickerID,
            kSecValueData as String: Data(token.utf8),
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    private func removeControllerToken(for tickerID: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "matt.TickerControl.controller-token",
            kSecAttrAccount as String: tickerID,
        ]
        SecItemDelete(query as CFDictionary)
    }

    private func tickerURL(_ tickerID: String, suffix: String = "") -> URL? {
        let identifier = tickerID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? tickerID
        return URL(string: "\(getBaseURL())/api/v2/tickers/\(identifier)\(suffix)")
    }

    private func authorizedRequest(url: URL, method: String, tickerID: String? = nil) -> URLRequest? {
        let identifier = tickerID ?? savedTickerID
        guard let identifier, let token = controllerToken(for: identifier) else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        return request
    }
    
    override init() {
        let savedURL = UserDefaults.standard.string(forKey: "serverURL") ?? "https://ticker.mattdicks.org"
        self.serverURL = savedURL
        super.init()
        
        // Initial Data Load
        fetchData()
        fetchLeagueOptions()
        fetchModeOptions()
        fetchDevices()
        fetchSpotifyStatus()
        
        // Adaptive poll: 0.5 s hyper-poll during burst window, 1 s otherwise.
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in
            Task { @MainActor in
                guard !self.isEditing else { return }
                let inBurst = Date() < self.burstPollUntil
                let interval = inBurst ? 0.5 : self.pollInterval(for: self.state.mode)
                if Date().timeIntervalSince(self.lastFetchTime) >= interval {
                    self.lastFetchTime = Date()
                    self.fetchData()
                    if self.leagueOptions.isEmpty { self.fetchLeagueOptions() }
                }
            }
        }
        // Poll device list every 5s to keep last_seen / online beacon fresh.
        devicesTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { _ in
            Task { @MainActor in
                if !self.isEditing { self.fetchDevices() }
            }
        }
    }
    private func pollInterval(for mode: String) -> TimeInterval {
        switch mode {
        case "music":                      return 1.0
        case "sports":                     return 1.0
        case "flights", "airports":         return 60.0
        case "stock":                       return 30.0
        case "weather", "clock":           return 600.0
        default:                           return 5.0
        }
    }
    /// Call this whenever the user switches modes. The timer will poll every 1 s
    /// for the next 30 s, giving the app (and the hardware board) fast feedback.
    func startBurstPolling() {
        burstPollUntil = Date().addingTimeInterval(30)
    }
    
    func getBaseURL() -> String {
        return serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: .init(charactersIn: "/"))
    }
    
    // === 1. FETCH DATA (Read) ===
    func fetchData() {
        let base = getBaseURL()
        if base.isEmpty { self.connectionStatus = "Invalid URL"; self.statusColor = .red; return }
        guard let tickerID = savedTickerID,
              controllerToken(for: tickerID) != nil,
              let url = tickerURL(tickerID, suffix: "/data") else {
            self.isServerReachable = true
            self.updateOverallStatus()
            return
        }
        
        URLSession.shared.dataTask(with: url) { data, _, error in
            if let error = error {
                DispatchQueue.main.async {
                    self.isServerReachable = false
                    self.updateOverallStatus()
                }
                return
            }
            
            guard let data = data else { return }
            
            do {
                let decoded = try JSONDecoder().decode(V2DataResponse.self, from: data)
                
                DispatchQueue.main.async {
                    self.isServerReachable = true
                    
                    // Sports keeps every selected game. Other modes use their own content family.
                    let isSportsFilterMode = decoded.settings.mode == "sports"
                    self.games = Array(decoded.games.enumerated()
                        .filter { $0.element.is_shown || isSportsFilterMode }
                        .sorted { left, right in
                            let g1 = left.element
                            let g2 = right.element
                            let p1 = self.isPinned(g1)
                            let p2 = self.isPinned(g2)
                            if p1 != p2 { return p1 }
                            if g1.is_shown != g2.is_shown { return g1.is_shown }
                            if g1.type == "stock_ticker" && g2.type != "stock_ticker" { return true }
                            if g1.state == "in" && g2.state != "in" { return true }
                            return left.offset < right.offset
                        }
                        .map(\.element))
                    
                    if !self.isEditing {
                        let decodedPins = decoded.settings.pinned_content_id.isEmpty ? [] : [self.normalizedPin(decoded.settings.pinned_content_id)]
                        self.pinnedGameIDs = Array(Set(decodedPins)).sorted()
                        self.state = decoded.settings
                        self.state.ticker_id = tickerID
                        self.state.pinned_games = decodedPins
                        self.state.pinned_game = decodedPins.first
                        if !self.state.my_teams.isEmpty {
                            print("📥 Synced State: \(self.state.my_teams.count) teams loaded.")
                        }
                        
                        // === FIX START: REMOVED LATCH LOGIC ===
                        // We deleted the lines that auto-saved savedTickerID here.
                        // This prevents the app from re-attaching to a ticker it doesn't own.
                        // ======================================
                        
                        if !decoded.settings.weather_city.isEmpty {
                            self.weatherLocInput = decoded.settings.weather_city
                        }
                    }
                    
                    self.updateOverallStatus()
                }
            } catch {
                print("❌ DECODING ERROR: \(error)")
                DispatchQueue.main.async { self.isServerReachable = true }
            }
        }.resume()
    }
    
    // === 2. TOGGLE TEAM (Edit) ===
    func toggleTeam(_ teamID: String) {
        // A. LOCK POLLING
        self.isEditing = true
        
        // B. UPDATE LOCAL UI INSTANTLY
        if let index = state.my_teams.firstIndex(of: teamID) {
            state.my_teams.remove(at: index)
        } else {
            state.my_teams.append(teamID)
        }
        
        // C. DEBOUNCE SAVE (Wait 1.5s after last tap) + start hyper polling
        startBurstPolling()
        saveDebounceTimer?.invalidate()
        saveDebounceTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: false) { [weak self] _ in
            self?.saveSettings()
        }
    }
    
    // === 3. TOGGLE PIN ===
    func togglePin(_ game: Game) {
        let scoped = pinID(for: game)
        if pinnedGameIDs.first == scoped {
            pinnedGameIDs.removeAll()
            state.pinned_games = []
            state.pinned_game = nil
            state.pinned_content_id = ""
            state.sports_presentation = "rotation"
        } else {
            pinnedGameIDs = [scoped]
            state.pinned_games = [scoped]
            state.pinned_game = scoped
            state.pinned_content_id = scoped
            state.sports_presentation = "pinned"
            state.mode = "sports"
        }
        startBurstPolling()
        saveSettings()
    }
    func sendPinnedGames() { saveSettings() }
    // === 4. SAVE SETTINGS (Write) ===
    func saveSettings() {
        self.isEditing = true   // LOCK: block polling while save is in-flight
        guard let validID = self.savedTickerID, let url = tickerURL(validID) else {
            self.isEditing = false
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: ["display_settings": v2DisplaySettingsPayload()])
            print("📤 Saving settings to \(url.absoluteString)")
            currentSaveTask?.cancel()
            currentSaveTask = URLSession.shared.dataTask(with: request) { data, response, error in
                if let error = error {
                    // Ignore cancellation errors — they mean a newer save superseded this one.
                    if (error as NSError).code == NSURLErrorCancelled { return }
                    print("❌ Save failed: \(error.localizedDescription)")
                }
                
                // === NEW SECURITY HANDLING ===
                if let httpResponse = response as? HTTPURLResponse {
                    if httpResponse.statusCode == 403 {
                        DispatchQueue.main.async {
                            print("⛔ Access Denied. Unpairing local app.")
                            self.isEditing = false
                            self.removeControllerToken(for: validID)
                            self.savedTickerID = nil
                            self.games = []
                            self.devices.removeAll()
                            self.updateOverallStatus()
                        }
                        return
                    }
                    if httpResponse.statusCode != 200 {
                        print("⛔ Save rejected. Status: \(httpResponse.statusCode)")
                    }
                }
                // =============================
                DispatchQueue.main.async {
                    self.isEditing = false
                    self.fetchData()
                }
            }
            currentSaveTask?.resume()
        } catch { print("Save Error") }
    }

    private func v2DisplaySettingsPayload(
        brightness: Double? = nil,
        scrollSpeed: Double? = nil,
        seamless: Bool? = nil,
        inverted: Bool? = nil,
        liveDelayMode: Bool? = nil,
        liveDelaySeconds: Int? = nil
    ) -> [String: Any] {
        let pinned = pinnedGameIDs.first ?? ""
        return [
            "active_sports": state.active_sports,
            "my_teams": state.my_teams,
            "mode": state.mode,
            "sports_filter": state.sports_filter,
            "sports_presentation": pinned.isEmpty ? "rotation" : "pinned",
            "pinned_content_id": pinned,
            "brightness": brightness ?? devices.first?.settings.brightness ?? 100,
            "inverted": inverted ?? devices.first?.settings.inverted ?? false,
            "timezone": TimeZone.current.identifier,
            "weather_city": state.weather_city,
            "weather_lat": state.weather_lat,
            "weather_lon": state.weather_lon,
            "airport_code_iata": state.airport_code_iata,
            "airport_code_icao": state.airport_code_icao,
            "airport_name": state.airport_name,
            "track_flight_id": state.track_flight_id,
            "track_guest_name": state.track_guest_name,
            "live_delay_mode": liveDelayMode ?? devices.first?.settings.live_delay_mode ?? false,
            "live_delay_seconds": liveDelaySeconds ?? devices.first?.settings.live_delay_seconds ?? 45,
            "scroll_seamless": seamless ?? state.scroll_seamless,
            "scroll_speed": scrollSpeed ?? state.scroll_speed,
            "score_alerts": true,
        ]
    }
    
    // --- STANDARD HELPERS ---
    
    func fetchLeagueOptions() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/v2/catalog/leagues") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            if let d = data, let decoded = try? JSONDecoder().decode(V2LeagueCatalog.self, from: d) {
                DispatchQueue.main.async {
                    self.leagueOptions = decoded.leagues
                    if let firstLeague = decoded.leagues.first(where: { $0.type == "sport" && $0.my_teams_enabled != false }) {
                        self.fetchTeams(for: firstLeague.id)
                    }
                }
            }
        }.resume()
    }
    
    func fetchTeams(for leagueID: String) {
        if allTeams[leagueID] != nil { return }
        let base = getBaseURL()
        let identifier = leagueID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? leagueID
        guard let url = URL(string: "\(base)/api/v2/catalog/leagues/\(identifier)/teams") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            if let d = data, let decoded = try? JSONDecoder().decode(V2TeamCatalog.self, from: d) {
                DispatchQueue.main.async { self.allTeams[leagueID] = decoded.teams }
            }
        }.resume()
    }

    func fetchModeOptions() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/v2/catalog/modes") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            if let data, let decoded = try? JSONDecoder().decode(V2ModeCatalog.self, from: data) {
                DispatchQueue.main.async {
                    self.modeSymbols = Dictionary(uniqueKeysWithValues: decoded.modes.map { ($0.id, $0.symbol) })
                }
            }
        }.resume()
    }

    func modeSymbol(for mode: String) -> String {
        modeSymbols[mode] ?? [
            "sports": "sportscourt.fill",
            "stock": "chart.line.uptrend.xyaxis",
            "music": "music.note",
            "flights": "airplane.arrival",
            "weather": "cloud.sun.fill",
            "clock": "clock.fill",
        ][mode, default: "circle"]
    }
    
    func fetchDevices() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/v2/tickers") else { return }
        
        URLSession.shared.dataTask(with: url) { data, _, _ in
            if let d = data, let decoded = try? JSONDecoder().decode(V2TickerList.self, from: d) {
                DispatchQueue.main.async {
                    // A valid /tickers response proves the server is reachable.
                    // Without this, a race where fetchDevices() finishes before
                    // fetchData() would call updateOverallStatus() while
                    // isServerReachable is still false, showing "Server Offline".
                    self.isServerReachable = true
                    let authorizedTickers = decoded.tickers.filter { self.controllerToken(for: $0.ticker_id) != nil }
                    self.devices = decoded.tickers
                        .filter { self.controllerToken(for: $0.ticker_id) != nil }
                        .map(\.tickerDevice)
                    if let activeID = self.savedTickerID,
                       !authorizedTickers.contains(where: { $0.ticker_id == activeID }) {
                        self.savedTickerID = authorizedTickers.first?.ticker_id
                    }
                    if authorizedTickers.isEmpty {
                        self.games = []
                    }
                    if self.isSportsOnly && self.state.mode != "sports" {
                        self.state.mode = "sports"
                        self.saveSettings()
                    }
                    self.updateOverallStatus()
                }
            }
        }.resume()
    }
    func updateOverallStatus() {
        if !isServerReachable { self.connectionStatus = "Server Offline"; self.statusColor = .red; return }
        // If we have devices OR a latched ID, we are effectively connected
        if devices.isEmpty && savedTickerID == nil { self.connectionStatus = "Server Online (No Ticker)"; self.statusColor = .orange; return }
        self.connectionStatus = "Connected • \(self.games.count) Items"; self.statusColor = .green
    }
    
    func updateWeatherAndSave() {
        let geocoder = CLGeocoder()
        
        // 1. IMMEDIATELY LOCK: Stops 0.5s updates from overwriting VM state
        self.isEditing = true
        
        geocoder.geocodeAddressString(weatherLocInput) { placemarks, error in
            DispatchQueue.main.async {
                if let pm = placemarks?.first, let loc = pm.location, let name = pm.locality ?? pm.name {
                    // Update internal values
                    self.state.weather_city = name
                    self.state.weather_lat = loc.coordinate.latitude
                    self.state.weather_lon = loc.coordinate.longitude
                }
                
                self.state.weather_location = self.weatherLocInput
                
                // 2. SEND TO SERVER
                self.saveSettings()
                
                // 3. EXTENDED LOCK: Give the server 2 seconds to finish writing
                // the new file to disk before we resume polling.
                DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
                    self.isEditing = false
                    self.fetchData() // Force one clean fetch
                }
            }
        }
    }
    
    func pairTicker(code: String, name: String) {
            let base = getBaseURL()
            guard let url = URL(string: "\(base)/api/v2/pairings/exchange") else {
                self.pairError = "Invalid Server URL"
                return
            }
            
            let body: [String: Any] = ["pairing_code": code]
            
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            
            do {
                req.httpBody = try JSONSerialization.data(withJSONObject: body)
            } catch {
                self.pairError = "Failed to encode pairing data"
                return
            }
            
            URLSession.shared.dataTask(with: req) { data, response, error in
                if let error = error {
                    DispatchQueue.main.async { self.pairError = "Network Error: \(error.localizedDescription)" }
                    return
                }
                
                // Check HTTP Status Code
                if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode != 201 {
                     DispatchQueue.main.async { self.pairError = "Server Error (Status: \(httpResponse.statusCode))" }
                     return
                }
                
                guard let d = data else {
                    DispatchQueue.main.async { self.pairError = "No data received from server" }
                    return
                }
                
                // Decode Response
                if let res = try? JSONDecoder().decode(PairingExchangeResponse.self, from: d), let newID = res.ticker_id {
                    DispatchQueue.main.async {
                        self.showPairSuccess = true
                        self.savedTickerID = newID
                        self.saveControllerToken(res.controller_token, for: newID)
                        self.updateTickerName(name, tickerID: newID)
                        self.fetchDevices()
                        self.fetchData()
                        self.fetchSpotifyStatus()
                    }
                } else {
                    DispatchQueue.main.async { self.pairError = "Failed to process server response" }
                }
            }.resume()
        }
    
    func pairTickerByID(id: String, name: String) {
            self.pairError = "Pair with the six-digit code shown on the Ticker."
        }
    
    func unpairTicker(id: String) {
        guard let url = tickerURL(id, suffix: "/pairing"),
              let request = authorizedRequest(url: url, method: "DELETE", tickerID: id) else {
            self.connectionStatus = "Unpair failed: ticker authorization is missing"
            self.statusColor = .red
            return
        }
        URLSession.shared.dataTask(with: request) { data, response, error in
            guard error == nil,
                  let status = (response as? HTTPURLResponse)?.statusCode,
                  status == 200,
                  let data,
                  let pairing = try? JSONDecoder().decode(PairingCodeResponse.self, from: data) else {
                let status = (response as? HTTPURLResponse)?.statusCode
                DispatchQueue.main.async {
                    self.connectionStatus = "Unpair failed\(status.map { \" (HTTP \($0))\" } ?? \"\")"
                    self.statusColor = .red
                }
                return
            }
            DispatchQueue.main.async {
                self.devices.removeAll { $0.id == id }
                self.games.removeAll()
                self.removeControllerToken(for: id)
                if self.savedTickerID == id {
                    self.savedTickerID = self.devices.first?.id
                }
                self.connectionStatus = "Ticker unpaired. Code: \(pairing.pairing_code)"
                self.statusColor = .orange
                self.fetchDevices()
                self.fetchData()
            }
        }.resume()
    }
    
    // ==========================================
    // MARK: - FIX: UPDATE SETTINGS (With Auth & Debugging)
    // ==========================================
    func updateDeviceSettings(id: String, brightness: Double? = nil, speed: Double? = nil, seamless: Bool? = nil, inverted: Bool? = nil, liveDelayMode: Bool? = nil, delaySeconds: Int? = nil) {
        guard let url = tickerURL(id) else {
            print("❌ Invalid URL for device update")
            return
        }
        let body = ["display_settings": v2DisplaySettingsPayload(
            brightness: brightness.map { $0 * 100 },
            scrollSpeed: speed,
            seamless: seamless,
            inverted: inverted,
            liveDelayMode: liveDelayMode,
            liveDelaySeconds: delaySeconds
        )]

        print("📤 Sending Update to \(id): \(body)")
        
        var req = URLRequest(url: url)
        req.httpMethod = "PATCH"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        do {
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        } catch {
            print("❌ JSON Serialization Error: \(error)")
            return
        }
        
        URLSession.shared.dataTask(with: req) { data, response, error in
            if let error = error {
                print("❌ Network Error: \(error.localizedDescription)")
                return
            }
            if let httpResponse = response as? HTTPURLResponse {
                if httpResponse.statusCode == 200 {
                    print("✅ Settings Saved Successfully")
                    // Refresh device list so toggles (inverted, live delay, etc.)
                    // reflect the confirmed server state immediately.
                    DispatchQueue.main.async { self.fetchDevices() }
                } else {
                    print("⛔ Server Rejected Request. Status: \(httpResponse.statusCode). Did you Pair?")
                }
            }
        }.resume()
    }

    private func updateTickerName(_ name: String, tickerID: String) {
        guard let url = tickerURL(tickerID) else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["name": name])
        URLSession.shared.dataTask(with: request).resume()
    }

    func fetchSpotifyStatus() {
        guard let tickerID = savedTickerID,
              let url = tickerURL(tickerID, suffix: "/integrations/spotify"),
              let request = authorizedRequest(url: url, method: "GET") else {
            spotifyStatus = "Connect a Ticker first"
            spotifyAccountName = nil
            spotifyAccounts = []
            return
        }
        URLSession.shared.dataTask(with: request) { data, response, _ in
            guard let data, let status = try? JSONDecoder().decode(SpotifyStatus.self, from: data) else {
                DispatchQueue.main.async { self.spotifyStatus = "Spotify unavailable" }
                return
            }
            DispatchQueue.main.async {
                self.spotifyStatus = status.connected ? "Connected" : "Not connected"
                self.spotifyAccountName = status.display_name
                self.spotifyAccounts = status.accounts
                self.spotifyError = nil
            }
        }.resume()
    }

    func connectSpotify() {
        guard let tickerID = savedTickerID,
              let url = tickerURL(tickerID, suffix: "/integrations/spotify/authorizations"),
              let request = authorizedRequest(url: url, method: "POST") else {
            spotifyError = "Pair with a Ticker before connecting Spotify."
            return
        }
        isConnectingSpotify = true
        spotifyError = nil
        URLSession.shared.dataTask(with: request) { data, response, error in
            guard error == nil,
                  let response = response as? HTTPURLResponse,
                  response.statusCode == 201,
                  let data,
                  let authorization = try? JSONDecoder().decode(SpotifyAuthorization.self, from: data) else {
                DispatchQueue.main.async {
                    self.isConnectingSpotify = false
                    self.spotifyError = "Spotify authorization could not start."
                }
                return
            }
            DispatchQueue.main.async {
                let session = ASWebAuthenticationSession(
                    url: authorization.authorization_url,
                    callbackURLScheme: "tickercontrol"
                ) { [weak self] callbackURL, error in
                    DispatchQueue.main.async {
                        guard let self else { return }
                        self.spotifyAuthorizationSession = nil
                        self.isConnectingSpotify = false
                        if let callbackURL {
                            self.handleSpotifyCallback(callbackURL)
                        } else {
                            self.spotifyError = error?.localizedDescription ?? "Spotify authorization was cancelled."
                        }
                    }
                }
                session.presentationContextProvider = self
                self.spotifyAuthorizationSession = session
                if !session.start() {
                    self.spotifyAuthorizationSession = nil
                    self.isConnectingSpotify = false
                    self.spotifyError = "Spotify authorization could not open."
                }
            }
        }.resume()
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        let windows = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
        return windows.first(where: \.isKeyWindow) ?? ASPresentationAnchor()
    }

    func disconnectSpotify(accountID: String? = nil) {
        guard let tickerID = savedTickerID,
              let url = tickerURL(
                tickerID,
                suffix: accountID.map { "/integrations/spotify/\($0)" } ?? "/integrations/spotify"
              ),
              let request = authorizedRequest(url: url, method: "DELETE") else { return }
        URLSession.shared.dataTask(with: request) { _, response, _ in
            DispatchQueue.main.async {
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.spotifyError = nil
                    self.fetchSpotifyStatus()
                } else {
                    self.spotifyError = "Spotify could not disconnect."
                }
            }
        }.resume()
    }

    func setSpotifyPriority(accountID: String?) {
        guard let tickerID = savedTickerID,
              let url = tickerURL(tickerID, suffix: "/integrations/spotify/priority"),
              var request = authorizedRequest(url: url, method: "PATCH") else { return }
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(
            withJSONObject: ["spotify_account_id": accountID as Any]
        )
        URLSession.shared.dataTask(with: request) { _, response, _ in
            DispatchQueue.main.async {
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.spotifyError = nil
                    self.fetchSpotifyStatus()
                } else {
                    self.spotifyError = "Spotify priority could not update."
                }
            }
        }.resume()
    }

    func handleSpotifyCallback(_ url: URL) {
        guard url.query?.contains("attempt_id=") == true else { return }
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        let status = components?.queryItems?.first(where: { $0.name == "status" })?.value
        if status == "connected" {
            fetchSpotifyStatus()
        } else {
            spotifyError = "Spotify authorization did not complete."
        }
    }

    func showPairCode(for tickerID: String) {
        guard let url = tickerURL(tickerID, suffix: "/pairing-code"),
              let request = authorizedRequest(url: url, method: "POST", tickerID: tickerID) else { return }
        URLSession.shared.dataTask(with: request) { data, response, _ in
            DispatchQueue.main.async {
                if (response as? HTTPURLResponse)?.statusCode == 201,
                   let data,
                   let pairing = try? JSONDecoder().decode(PairingCodeResponse.self, from: data) {
                    self.pairCodeAlertMessage = pairing.pairing_code
                } else {
                    self.pairCodeAlertMessage = "A pairing code could not be created."
                }
                self.showingPairCodeAlert = true
            }
        }.resume()
    }
    
    // ==========================================
    // MARK: - REBOOT
    // ==========================================
    func reboot() {
        guard let tickerID = savedTickerID,
              let url = tickerURL(tickerID, suffix: "/commands/reboot"),
              let request = authorizedRequest(url: url, method: "POST") else {
            connectionStatus = "Pair this ticker before requesting a reboot."
            statusColor = .orange
            return
        }
        URLSession.shared.dataTask(with: request) { _, response, error in
            DispatchQueue.main.async {
                if error == nil, (response as? HTTPURLResponse)?.statusCode == 201 {
                    self.connectionStatus = "Reboot requested. The ticker will restart on its next poll."
                    self.statusColor = .green
                } else {
                    self.connectionStatus = "The reboot request failed."
                    self.statusColor = .red
                }
            }
        }.resume()
    }
    
    func sendDebug() {
        connectionStatus = "Debug controls are not available from the V2 API"
        statusColor = .orange
    }
}
// ==========================================
// MARK: - 3. UI COMPONENTS
// ==========================================
struct NativeLiquidGlass: ViewModifier {
    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)
        return content
            .background(shape.fill(.regularMaterial).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5))
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape)
    }
}
extension View { func liquidGlass() -> some View { modifier(NativeLiquidGlass()) } }
func weatherIcon(for condition: String) -> String {
    let c = condition.uppercased()
    if c.contains("CLEAR") || c.contains("SUNNY") { return "sun.max.fill" }
    if c.contains("PARTLY") { return "cloud.sun.fill" }
    if c.contains("CLOUD") || c.contains("OVERCAST") { return "cloud.fill" }
    if c.contains("RAIN") || c.contains("DRIZZLE") || c.contains("SHOWER") { return "cloud.rain.fill" }
    if c.contains("SNOW") { return "cloud.snow.fill" }
    if c.contains("THUNDER") { return "cloud.bolt.rain.fill" }
    if c.contains("FOG") || c.contains("MIST") || c.contains("HAZE") { return "cloud.fog.fill" }
    if c.contains("FREEZING") { return "thermometer.snowflake" }
    return "cloud.fill"
}
struct SituationPill: View {
    let text: String; let color: Color
    var body: some View {
        Text(text).font(.system(size: 10, weight: .black)).foregroundColor(color)
            .padding(.horizontal, 6).padding(.vertical, 3).background(color.opacity(0.2))
            .cornerRadius(4).overlay(RoundedRectangle(cornerRadius: 4).stroke(color.opacity(0.3), lineWidth: 1))
    }
}
struct FootballDownContext: View {
    let downDist: String?
    let isRedZone: Bool

    var body: some View {
        if let downDist, !downDist.isEmpty {
            SituationPill(text: downDist, color: isRedZone ? .red : .yellow)
        }
    }
}
struct BaseballCountContext: View {
    let balls: Int
    let strikes: Int
    let outs: Int

    var body: some View {
        HStack(spacing: 4) {
            HStack(spacing: 3) {
                count("B", value: balls, color: .green)
                count("S", value: strikes, color: .yellow)
                count("O", value: outs, color: .red)
            }
            .padding(.horizontal, 6).padding(.vertical, 3)
            .background(Color.white.opacity(0.12))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color.white.opacity(0.16), lineWidth: 1))
            .cornerRadius(4)
        }
    }

    @ViewBuilder private func count(_ label: String, value: Int, color: Color) -> some View {
        Text(label).font(.system(size: 8, weight: .black)).foregroundStyle(color)
        Text("\(value)").font(.system(size: 10, weight: .black)).foregroundStyle(.white)
    }
}
struct ShootoutBubbles: View {
    let results: [String]
    let maxDots: Int
    var body: some View {
        HStack(spacing: 2) {
            ForEach(0..<max(maxDots, results.count), id: \.self) { i in
                if i < results.count {
                    let res = results[i]
                    if res == "goal" {
                        Image(systemName: "checkmark.circle.fill").symbolRenderingMode(.palette).foregroundStyle(.white, .green).font(.system(size: 8))
                    } else if res == "miss" {
                        Image(systemName: "xmark.circle.fill").symbolRenderingMode(.palette).foregroundStyle(.white, .red).font(.system(size: 8))
                    } else {
                        Image(systemName: "circle").foregroundStyle(.gray).font(.system(size: 8))
                    }
                } else {
                    Image(systemName: "circle").foregroundStyle(.gray.opacity(0.5)).font(.system(size: 8))
                }
            }
        }
    }
}
struct TabButton: View {
    let icon: String; let label: String; let idx: Int; @Binding var sel: Int
    var body: some View { Button { sel = idx } label: { VStack(spacing: 4) { Image(systemName: icon).font(.system(size: 20)); Text(label).font(.caption2) }.frame(maxWidth: .infinity).foregroundColor(sel == idx ? .white : .gray).padding(.vertical, 8).background(sel == idx ? Color.white.opacity(0.15) : Color.clear).cornerRadius(12) } }
}
struct FilterBtn: View {
    let title: String; let val: String; let cur: String; let act: () -> Void
    var body: some View { Button(action: act) { Text(title).font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12).background(cur == val ? Color(red: 0.0, green: 0.47, blue: 1.0) : Color.white.opacity(0.05)).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous)).overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(cur == val ? Color.blue : Color.white.opacity(0.1), lineWidth: 1)).foregroundColor(.white) } }
}
struct ScrollBtn: View {
    let title: String; let val: Bool; let cur: Bool; let act: () -> Void
    var body: some View { Button(action: act) { Text(title).font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12).background(cur == val ? Color(red: 0.0, green: 0.47, blue: 1.0) : Color.white.opacity(0.05)).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous)).overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(cur == val ? Color.blue : Color.white.opacity(0.1), lineWidth: 1)).foregroundColor(.white) } }
}
struct TeamLogoView: View {
    let url: String?; let abbr: String; let size: CGFloat
    var body: some View { AsyncImage(url: URL(string: url ?? "")) { phase in if let image = phase.image { image.resizable().scaledToFit() } else { Text(abbr).font(.system(size: size * 0.4, weight: .bold)).foregroundColor(.white.opacity(0.8)) } }.frame(width: size, height: size) }
}
struct MusicNowPlayingCard: View {
    let game: Game

    private var isPlaying: Bool { game.status == "playing" }
    private var progress: Double {
        guard let duration = game.duration, duration > 0 else { return 0 }
        return min(max(Double(game.progress ?? 0) / duration, 0), 1)
    }

    var body: some View {
        HStack(spacing: 14) {
            AsyncImage(url: URL(string: game.cover ?? "")) { phase in
                if let image = phase.image {
                    image.resizable().scaledToFill()
                } else {
                    Image(systemName: "music.note")
                        .font(.title2).foregroundStyle(.green)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color.green.opacity(0.14))
                }
            }
            .frame(width: 58, height: 58)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Image(systemName: isPlaying ? "waveform" : "pause.fill")
                        .font(.caption).foregroundStyle(isPlaying ? .green : .secondary)
                    Text(isPlaying ? "NOW PLAYING" : "SPOTIFY")
                        .font(.caption2.weight(.bold)).foregroundStyle(isPlaying ? .green : .secondary)
                }
                Text(game.name ?? "No active Spotify playback")
                    .font(.headline).foregroundStyle(.white).lineLimit(1)
                Text(game.artist ?? "Choose an account in Music settings")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                ProgressView(value: progress)
                    .tint(.green).opacity(game.duration == nil ? 0 : 1)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(Color.green.opacity(isPlaying ? 0.55 : 0.2), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
struct StockFeedCard: View {
    let game: Game

    private var isUp: Bool { !game.away_score.contains("-") }
    private var changeColor: Color { isUp ? .green : .red }

    var body: some View {
        HStack(spacing: 14) {
            AsyncImage(url: URL(string: game.safeHomeLogo)) { phase in
                if let image = phase.image {
                    image.resizable().scaledToFit().padding(7)
                } else {
                    Text(game.safeHomeAbbr.prefix(4)).font(.caption.weight(.heavy))
                }
            }
            .frame(width: 54, height: 54)
            .background(changeColor.opacity(0.13))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))

            VStack(alignment: .leading, spacing: 5) {
                Text("MARKETS").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text(game.safeHomeAbbr).font(.headline).foregroundStyle(.white)
                Text(game.status.isEmpty ? "Live quote" : game.status)
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 5) {
                Text("$\(game.home_score)").font(.headline.weight(.bold)).foregroundStyle(.white)
                Label("\(game.situation?.change ?? "")  \(game.away_score)", systemImage: isUp ? "arrow.up.right" : "arrow.down.right")
                    .font(.caption2.weight(.bold)).foregroundStyle(changeColor)
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(changeColor.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
struct WeatherLocationCard: View {
    let game: Game

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: weatherIcon(for: game.status))
                .font(.system(size: 30)).foregroundStyle(.yellow)
                .frame(width: 54, height: 54)
                .background(Color.blue.opacity(0.15))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 5) {
                Text("LOCAL WEATHER").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text(game.safeAwayAbbr.isEmpty ? "Weather" : game.safeAwayAbbr)
                    .font(.headline).foregroundStyle(.white)
                Text(game.status.capitalized).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Text("NOW").font(.caption2.weight(.bold)).foregroundStyle(.blue)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.blue.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

}
struct WeatherCurrentCard: View {
    let game: Game

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: "thermometer.medium")
                .font(.system(size: 28)).foregroundStyle(.orange)
                .frame(width: 54, height: 54)
                .background(Color.orange.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 5) {
                Text("CURRENT TEMPERATURE").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text("Feels like \(game.feels ?? game.safeHomeAbbr)°")
                    .font(.headline).foregroundStyle(.white)
                Text(currentDetails).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Text("\(game.safeHomeAbbr)°")
                .font(.system(size: 30, weight: .bold, design: .rounded)).foregroundStyle(.white)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.orange.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private var currentDetails: String {
        [game.wind.map { "Wind \($0) mph" }, game.humidity.map { "Humidity \($0)%" }]
            .compactMap { $0 }.joined(separator: " · ")
    }
}
struct WeatherTodayCard: View {
    let game: Game

    private var today: WeatherForecast? { game.forecast?.first }

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: weatherIcon(for: today?.icon ?? game.status))
                .font(.system(size: 28)).foregroundStyle(.cyan)
                .frame(width: 54, height: 54)
                .background(Color.cyan.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 5) {
                Text("\(today?.day?.uppercased() ?? "TODAY") FORECAST")
                    .font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text("High \(today?.high ?? "—")°  ·  Low \(today?.low ?? "—")°")
                    .font(.headline).foregroundStyle(.white)
                Text(today?.pop.map { "\($0)% precipitation chance" } ?? "Forecast updating")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.cyan.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
struct TrackedFlightFeedCard: View {
    let game: Game

    private var active: Bool { game.is_live == true }
    private var delayed: Bool { game.is_delayed == true || (game.delay_min ?? 0) >= 15 }
    private var accent: Color { delayed ? .red : (active ? .orange : .secondary) }
    private var progress: Double { min(max(Double(game.progress ?? 0) / 100, 0), 1) }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 10) {
                Image(systemName: "airplane.circle.fill").font(.title2).foregroundStyle(accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(game.guest_name ?? game.id).font(.headline).foregroundStyle(.white)
                    Text(game.route ?? "Tracked flight").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Text(game.status.uppercased()).font(.caption2.weight(.bold)).foregroundStyle(accent)
            }
            HStack {
                Text(game.origin_city ?? "—").font(.caption.weight(.bold)).foregroundStyle(.white)
                Spacer()
                Image(systemName: "airplane").font(.caption).foregroundStyle(accent)
                Spacer()
                Text(game.dest_city ?? "—").font(.caption.weight(.bold)).foregroundStyle(.white)
            }
            ProgressView(value: progress).tint(accent).opacity(game.progress == nil ? 0 : 1)
            if let eta = game.eta_str, !eta.isEmpty {
                Text("ETA \(eta)").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(accent.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
struct AirportLocationCard: View {
    let game: Game

    private var airport: AirportWeather? { game.airportWeather }

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: "airplane.departure").font(.title2).foregroundStyle(.cyan)
                .frame(width: 54, height: 54)
                .background(Color.cyan.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text("AIRPORT ACTIVITY").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text(airport?.iata ?? "AIRPORT").font(.headline).foregroundStyle(.white)
                Text(airport?.city ?? "Live airport activity").font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            if let weather = airport, !weather.away_abbr.orEmpty.isEmpty {
                VStack(alignment: .trailing, spacing: 4) {
                    Image(systemName: weatherIcon(for: weather.status ?? "")).foregroundStyle(.cyan)
                    Text(weather.away_abbr ?? "").font(.caption.weight(.bold)).foregroundStyle(.white)
                }
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.cyan.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
struct AirportScheduleFeedCard: View {
    let title: String
    let icon: String
    let flights: [AirportFlight]
    let color: Color

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icon).font(.title2).foregroundStyle(color)
                .frame(width: 54, height: 54)
                .background(color.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.caption2.weight(.bold)).foregroundStyle(color)
                Text(flights.first?.home_abbr ?? "No scheduled flights")
                    .font(.headline).foregroundStyle(.white).lineLimit(1)
                Text(destinationText).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            Text("\(flights.count)").font(.title3.weight(.bold)).foregroundStyle(color)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(color.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private var destinationText: String {
        guard let first = flights.first else { return "Waiting for schedule" }
        return first.other_iata ?? first.altitude ?? "Airport schedule"
    }
}

private extension String? {
    var orEmpty: String { self ?? "" }
}
struct GameRow: View {
    let game: Game
    let leagueLabel: String?
    var isPinned: Bool = false
    
    // Drives the continuous animation for the music waveform
    @State private var waveformActive = false
    var activeSituation: String {
        guard let s = game.situation else { return "" }
        if let en = s.emptyNet, en { return "EMPTY NET" }
        if let pp = s.powerPlay, pp { return "PWR PLAY" }
        return ""
    }
    
    var situationColor: Color {
        if let s = game.situation {
            if s.isRedZone == true { return Color.red }
            if s.emptyNet == true { return Color.red }
        }
        return Color.yellow
    }
    
    func ownsActiveTeam(isHome: Bool) -> Bool {
        guard let s = game.situation else { return false }
        let activeTeam = (s.activeTeam ?? "").trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        let team = (isHome ? game.safeHomeAbbr : game.safeAwayAbbr).uppercased()
        return !activeTeam.isEmpty && activeTeam == team
    }

    var isFootball: Bool {
        ["nfl", "ncf_fbs", "ncf_fcs"].contains(game.sport)
    }

    var isBaseball: Bool { game.sport == "mlb" }

    var hasBaseballCount: Bool {
        guard let s = game.situation else { return false }
        return s.balls != nil && s.strikes != nil && s.outs != nil
    }

    func ownsFootballContext(isHome: Bool) -> Bool {
        guard isFootball, game.situation != nil else { return false }
        return ownsActiveTeam(isHome: isHome)
    }

    @ViewBuilder func teamLiveContext(isHome: Bool) -> some View {
        if ownsFootballContext(isHome: isHome), let s = game.situation {
            FootballDownContext(downDist: s.downDist, isRedZone: s.isRedZone == true)
        } else if isBaseball, hasBaseballCount, ownsActiveTeam(isHome: isHome), let s = game.situation,
                  let balls = s.balls, let strikes = s.strikes, let outs = s.outs {
            BaseballCountContext(balls: balls, strikes: strikes, outs: outs)
        } else if !activeSituation.isEmpty, ownsActiveTeam(isHome: isHome) {
            SituationPill(text: activeSituation, color: situationColor)
        }
    }
    
    var isSituationGlobal: Bool {
        guard game.situation != nil else { return false }
        if isFootball || isBaseball { return false }
        return !activeSituation.isEmpty && !ownsActiveTeam(isHome: true) && !ownsActiveTeam(isHome: false)
    }
    
    var formattedSport: String {
        if let label = leagueLabel { return label }
        switch game.sport {
        case "ncf_fbs": return "FBS"
        case "ncf_fcs": return "FCS"
        case "soccer_epl": return "EPL"
        case "soccer_champ": return "EFL"
        case "soccer_wc": return "FIFA"
        case "hockey_olympics": return "OLY"
        default: return game.sport.uppercased()
        }
    }
    
    var isLive: Bool { return game.state == "in" }
    var isSoccer: Bool { return game.sport.contains("soccer") }
    
    func prioritizeVibrantColor(primary: String?, alternate: String?) -> Color {
        let pColor = Color(hex: primary ?? "#000000")
        let aColor = Color(hex: alternate ?? "#000000")
        if pColor.isGrayscaleOrBlack && !aColor.isGrayscaleOrBlack { return aColor }
        return pColor
    }
    
    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)
        
        if game.type == "stock_ticker" {
            // MARK: - STOCK CARD
            HStack(spacing: 12) {
                Capsule().fill(Color.blue).frame(width: 4, height: 55)
                if let u = game.home_logo, !u.isEmpty {
                    TeamLogoView(url: u, abbr: game.safeHomeAbbr, size: 32)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(game.safeHomeAbbr).font(.headline).bold().foregroundColor(.white)
                    Text(game.tourney_name ?? "MARKET").font(.caption2).bold().foregroundColor(.gray)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    Text("$\(game.home_score)").font(.title3).bold().foregroundColor(.white)
                    HStack(spacing: 4) {
                        let changePct = game.away_score
                        let changeAmt = game.situation?.change ?? ""
                        let isUp = !changePct.contains("-")
                        Image(systemName: isUp ? "arrowtriangle.up.fill" : "arrowtriangle.down.fill").font(.system(size: 8))
                        Text("\(changeAmt) (\(changePct))").font(.caption).bold()
                    }
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(game.away_score.contains("-") ? Color.red.opacity(0.2) : Color.green.opacity(0.2))
                    .foregroundColor(game.away_score.contains("-") ? .red : .green)
                    .cornerRadius(6)
                }
            }
            .padding(12).background(Color(white: 0.15))
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)
            
        } else if game.type == "flight_visitor" {
            // MARK: - FLIGHT TRACKER CARD
            let isInAir = game.is_live == true
            let isDelayed = game.is_delayed == true || (game.delay_min ?? 0) >= 15
            let statusLower = game.status.lowercased()
            let isIdleStatus = ["pending", "no flight", "select flight", "waiting"].contains(statusLower)
            let progressPct = Double(game.progress ?? 0) / 100.0
            let planeColor: Color = isDelayed ? .red : (isInAir ? .orange : .gray)
            let statusBg: Color = isDelayed ? Color.red.opacity(0.2) : (isInAir ? Color.orange.opacity(0.2) : (isIdleStatus ? Color.gray.opacity(0.2) : Color.green.opacity(0.2)))
            let statusFg: Color = isDelayed ? .red : (isInAir ? .orange : (isIdleStatus ? .gray : .green))
            
            VStack(alignment: .leading, spacing: 10) {
                // Header
                HStack(spacing: 8) {
                    Image(systemName: "airplane.circle.fill")
                        .font(.title2)
                        .foregroundStyle(planeColor)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(game.guest_name ?? game.id)
                            .font(.headline).bold().foregroundColor(.white)
                        Text(game.route ?? "")
                            .font(.caption).foregroundColor(.gray)
                    }
                    Spacer()
                    Text(game.status)
                        .font(.system(size: 11, weight: .bold))
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(statusBg)
                        .foregroundColor(statusFg)
                        .cornerRadius(6)
                }
                
                // Route visualization
                HStack(spacing: 0) {
                    Text(game.origin_city ?? "?")
                        .font(.system(size: 11, weight: .bold)).foregroundColor(.white)
                    Spacer()
                    Text(game.dest_city ?? "?")
                        .font(.system(size: 11, weight: .bold)).foregroundColor(.white)
                }
                
                // Progress bar
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.white.opacity(0.1)).frame(height: 6)
                    GeometryReader { geo in
                        Capsule().fill(planeColor)
                            .frame(width: max(6, geo.size.width * progressPct), height: 6)
                    }.frame(height: 6)
                    // Airplane icon on progress
                    GeometryReader { geo in
                        Image(systemName: "airplane")
                            .font(.system(size: 12))
                            .foregroundColor(planeColor)
                            .rotationEffect(.degrees(0))
                            .offset(x: max(0, min(geo.size.width - 14, geo.size.width * progressPct - 7)), y: -10)
                    }.frame(height: 6)
                }
                
                // Stats row
                HStack(spacing: 16) {
                    if let alt = game.alt, alt > 0 {
                        HStack(spacing: 4) {
                            Image(systemName: "arrow.up").font(.system(size: 9))
                            Text("\(alt.formatted()) ft").font(.system(size: 11, weight: .medium))
                        }.foregroundStyle(.gray)
                    }
                    if let spd = game.speed, spd > 0 {
                        HStack(spacing: 4) {
                            Image(systemName: "speedometer").font(.system(size: 9))
                            Text("\(spd) mph").font(.system(size: 11, weight: .medium))
                        }.foregroundStyle(.gray)
                    }
                    if let dist = game.dist, dist > 0 {
                        HStack(spacing: 4) {
                            Image(systemName: "location").font(.system(size: 9))
                            Text("\(dist) mi").font(.system(size: 11, weight: .medium))
                        }.foregroundStyle(.gray)
                    }
                    Spacer()
                    if let eta = game.eta_str, !eta.isEmpty {
                        HStack(spacing: 4) {
                            Image(systemName: "clock").font(.system(size: 9))
                            Text("ETA \(eta)").font(.system(size: 11, weight: .bold))
                        }.foregroundStyle(.orange)
                    }
                }
            }
            .padding(14)
            .background(
                LinearGradient(gradient: Gradient(colors: [Color.orange.opacity(0.15), Color(white: 0.12)]), startPoint: .topLeading, endPoint: .bottomTrailing)
            )
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [Color.orange.opacity(0.4), Color.white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)
            
        } else if game.type == "flight_weather" || game.type == "flight_arrival" || game.type == "flight_departure" {
            // Handled by AirportBoardView in HomeView — skip individual rendering
            EmptyView()
            
        } else if game.type == "leaderboard" {
            // MARK: - LEADERBOARD CARD
            HStack(spacing: 12) {
                Capsule().fill(isPinned ? Color.yellow : (game.is_shown ? Color.green : Color.red)).frame(width: 4, height: 55)
                VStack(alignment: .leading) {
                    Text(game.tourney_name ?? "Event").font(.headline).bold().foregroundColor(.white)
                    Text(game.status).font(.caption).foregroundColor(.gray)
                }
                Spacer()
                Text(formattedSport).font(.system(size: 14, weight: .bold)).foregroundColor(.white).padding(6).background(Color.white.opacity(0.1)).cornerRadius(6)
            }
            .padding(12).background(Color(white: 0.15))
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)
            
        } else if game.type == "music" {
            // MARK: - MUSIC CARD
            let isPaused = game.status.lowercased().contains("paused") || game.status.isEmpty
            
            HStack(spacing: 12) {
                Capsule().fill(Color(hex: "#1DB954")).frame(width: 4, height: 60)
                
                AsyncImage(url: URL(string: game.safeHomeLogo)) { phase in
                    if let image = phase.image {
                        image.resizable().aspectRatio(contentMode: .fill)
                    } else {
                        ZStack {
                            Color(white: 0.2)
                            Image(systemName: "music.note").foregroundStyle(.gray)
                        }
                    }
                }
                .frame(width: 50, height: 50)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1), lineWidth: 1))
                
                VStack(alignment: .leading, spacing: 4) {
                    Text(game.safeAwayAbbr)
                        .font(.headline).bold().foregroundColor(.white)
                        .lineLimit(1)
                    
                    HStack(spacing: 6) {
                        Image(systemName: "mic.fill").font(.caption2).foregroundColor(.gray)
                        Text(game.safeHomeAbbr)
                            .font(.subheadline).foregroundColor(.gray)
                            .lineLimit(1)
                    }
                }
                
                Spacer()
                
                VStack(alignment: .trailing, spacing: 8) {
                    HStack(alignment: .center, spacing: 3) {
                        ForEach(0..<5) { i in
                            Capsule()
                                .fill(Color(hex: "#1DB954"))
                                .frame(width: 3, height: (!isPaused && waveformActive) ? CGFloat.random(in: 12...24) : 4)
                                .animation(
                                    !isPaused
                                    ? .easeInOut(duration: CGFloat.random(in: 0.4...0.7)).repeatForever(autoreverses: true).delay(Double(i) * 0.05)
                                    : .default,
                                    value: waveformActive
                                )
                        }
                    }
                    .frame(height: 24)
                    .onAppear { waveformActive = true }
                    
                    Text(game.status)
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundColor(.white.opacity(0.9))
                        .padding(.horizontal, 6).padding(.vertical, 4)
                        .background(Color(hex: "#1DB954").opacity(0.2))
                        .cornerRadius(6)
                }
            }
            .padding(12).background(Color(white: 0.15))
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)
            
        } else {
            // MARK: - STANDARD SPORTS/WEATHER/CLOCK
            let homeColor = prioritizeVibrantColor(primary: game.home_color, alternate: game.home_alt_color)
            let awayColor = prioritizeVibrantColor(primary: game.away_color, alternate: game.away_alt_color)
            let bg = LinearGradient(gradient: Gradient(colors: [awayColor.opacity(0.3), homeColor.opacity(0.3)]), startPoint: .leading, endPoint: .trailing)
            HStack(spacing: 12) {
                Capsule().fill(isPinned ? Color.yellow : (game.is_shown ? Color.green : Color.red)).frame(width: 4, height: 55)
                if game.sport == "weather" {
                    HStack {
                        Image(systemName: game.situation?.icon == "sun" ? "sun.max.fill" : "cloud.fill").font(.title).foregroundColor(.yellow)
                        VStack(alignment: .leading) {
                            Text(game.safeAwayAbbr).font(.headline).bold().foregroundColor(.white)
                            Text(game.status).font(.caption).foregroundColor(.gray)
                        }
                        Spacer()
                        Text(game.safeHomeAbbr).font(.system(size: 24, weight: .bold)).foregroundColor(.white)
                    }
                } else if game.sport == "clock" {
                    HStack {
                        Image(systemName: "clock.fill").font(.title).foregroundColor(.blue)
                        Text("Clock Mode Active").font(.headline).bold().foregroundColor(.white)
                        Spacer()
                    }
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            TeamLogoView(url: game.safeAwayLogo, abbr: game.safeAwayAbbr, size: 22)
                            Text(game.safeAwayAbbr).font(.headline).bold().foregroundColor(.white)
                            if let so = game.situation?.shootout, let awayRes = so.away {
                                ShootoutBubbles(results: awayRes, maxDots: isSoccer ? 5 : 3)
                                    .padding(.horizontal, 4).padding(.vertical, 2)
                                    .background(Color.black.opacity(0.3)).cornerRadius(4)
                            }
                            else { teamLiveContext(isHome: false) }
                            Spacer(); Text(game.away_score).font(.headline).bold().foregroundColor(.white)
                        }
                        HStack {
                            TeamLogoView(url: game.safeHomeLogo, abbr: game.safeHomeAbbr, size: 22)
                            Text(game.safeHomeAbbr).font(.headline).bold().foregroundColor(.white)
                            if let so = game.situation?.shootout, let homeRes = so.home {
                                ShootoutBubbles(results: homeRes, maxDots: isSoccer ? 5 : 3)
                                    .padding(.horizontal, 4).padding(.vertical, 2)
                                    .background(Color.black.opacity(0.3)).cornerRadius(4)
                            }
                            else { teamLiveContext(isHome: true) }
                            Spacer(); Text(game.home_score).font(.headline).bold().foregroundColor(.white)
                        }
                    }
                    VStack(alignment: .trailing, spacing: 4) {
                        Text(game.status)
                            .font(.caption).bold().padding(.horizontal, 8).padding(.vertical, 4)
                            .background(isLive ? Color.red.opacity(0.1) : Color.white.opacity(0.1))
                            .cornerRadius(6).foregroundColor(.white)
                        Text(formattedSport).font(.caption2).foregroundStyle(.gray).multilineTextAlignment(.trailing)
                        if isSituationGlobal { SituationPill(text: activeSituation, color: situationColor) }
                    }.frame(width: 80, alignment: .trailing)
                }
            }
            .padding(12).background(bg)
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)
        }
    }
}
// ==========================================
// MARK: - AIRPORT BOARD VIEW
// ==========================================
struct AirportBoardView: View {
    let flights: [Game]
    
    private var weatherItem: Game? { flights.first(where: { $0.type == "flight_weather" }) }
    private var arrivals: [Game] { flights.filter { $0.type == "flight_arrival" } }
    private var departures: [Game] { flights.filter { $0.type == "flight_departure" } }
    
    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)
        
        VStack(spacing: 12) {
            // ====== CARD 1: AIRPORT INFO ======
            if let wx = weatherItem {
                VStack(spacing: 0) {
                    // Top: Airport name banner
                    HStack(spacing: 0) {
                        HStack(spacing: 10) {
                            ZStack {
                                Circle()
                                    .fill(
                                        RadialGradient(gradient: Gradient(colors: [Color.cyan.opacity(0.25), Color.cyan.opacity(0.05)]), center: .center, startRadius: 0, endRadius: 24)
                                    )
                                    .frame(width: 44, height: 44)
                                Image(systemName: "airplane")
                                    .font(.system(size: 20, weight: .semibold))
                                    .foregroundStyle(.cyan)
                                    .rotationEffect(.degrees(-45))
                            }
                            
                            VStack(alignment: .leading, spacing: 2) {
                                Text(wx.safeHomeAbbr)
                                    .font(.system(size: 20, weight: .bold, design: .rounded))
                                    .foregroundColor(.white)
                                Text("LIVE ACTIVITY")
                                    .font(.system(size: 9, weight: .heavy, design: .rounded))
                                    .tracking(2)
                                    .foregroundStyle(.cyan.opacity(0.5))
                            }
                        }
                        
                        Spacer()
                        
                        // Weather block
                        HStack(spacing: 10) {
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(wx.status)
                                    .font(.system(size: 11, weight: .medium))
                                    .foregroundColor(.gray)
                                Text(wx.safeAwayAbbr)
                                    .font(.system(size: 26, weight: .bold, design: .rounded))
                                    .foregroundColor(.white)
                            }
                            Image(systemName: weatherIcon(for: wx.status))
                                .font(.system(size: 24))
                                .symbolRenderingMode(.hierarchical)
                                .foregroundStyle(.cyan)
                        }
                    }
                    .padding(16)
                }
                .background(
                    LinearGradient(gradient: Gradient(colors: [
                        Color.cyan.opacity(0.10),
                        Color(white: 0.07)
                    ]), startPoint: .topLeading, endPoint: .bottomTrailing)
                )
                .overlay(
                    shape.strokeBorder(
                        LinearGradient(gradient: Gradient(colors: [Color.cyan.opacity(0.4), Color.cyan.opacity(0.08)]),
                                       startPoint: .topLeading, endPoint: .bottomTrailing),
                        lineWidth: 1
                    )
                )
                .clipShape(shape)
                .shadow(color: Color.cyan.opacity(0.06), radius: 12, x: 0, y: 6)
            }
            
            // ====== CARD 2: ARRIVALS ======
            if !arrivals.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    // Header
                    HStack(spacing: 8) {
                        Image(systemName: "airplane.arrival")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.green)
                        Text("ARRIVALS")
                            .font(.system(size: 11, weight: .heavy, design: .rounded))
                            .tracking(1.5)
                            .foregroundStyle(.green.opacity(0.8))
                        Spacer()
                        Text("\(arrivals.count)")
                            .font(.system(size: 11, weight: .bold, design: .rounded))
                            .foregroundStyle(.green.opacity(0.5))
                    }
                    .padding(.horizontal, 16).padding(.top, 14).padding(.bottom, 10)
                    
                    // Divider
                    Rectangle().fill(Color.green.opacity(0.1)).frame(height: 1)
                    
                    // Flight rows
                    ForEach(Array(arrivals.enumerated()), id: \.element.id) { index, arr in
                        HStack(spacing: 12) {
                            // Flight number
                            Text(arr.safeAwayAbbr)
                                .font(.system(size: 14, weight: .bold, design: .monospaced))
                                .foregroundColor(.white)
                                .frame(width: 80, alignment: .leading)
                            
                            // Route
                            HStack(spacing: 6) {
                                Text(arr.safeHomeAbbr)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundColor(.white.opacity(0.6))
                                Image(systemName: "arrow.right")
                                    .font(.system(size: 9, weight: .bold))
                                    .foregroundStyle(.green.opacity(0.4))
                                Image(systemName: "mappin.circle.fill")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.green.opacity(0.6))
                            }
                            
                            Spacer()
                            
                            // Status pill
                            let arrDelayed = arr.status.uppercased() == "DELAYED"
                            HStack(spacing: 4) {
                                Circle().fill(arrDelayed ? Color.orange : Color.green).frame(width: 4, height: 4)
                                Text(arrDelayed ? "DELAYED" : "INBOUND")
                                    .font(.system(size: 8, weight: .heavy, design: .rounded))
                            }
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background((arrDelayed ? Color.orange : Color.green).opacity(0.1))
                            .foregroundColor(arrDelayed ? .orange : .green)
                            .clipShape(Capsule())
                        }
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        
                        if index < arrivals.count - 1 {
                            Rectangle().fill(Color.white.opacity(0.04)).frame(height: 1).padding(.horizontal, 16)
                        }
                    }
                    
                    Spacer().frame(height: 6)
                }
                .background(Color(white: 0.08))
                .overlay(shape.strokeBorder(Color.green.opacity(0.12), lineWidth: 1))
                .clipShape(shape)
                .shadow(color: Color.black.opacity(0.1), radius: 8, x: 0, y: 4)
            }
            
            // ====== CARD 3: DEPARTURES ======
            if !departures.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    // Header
                    HStack(spacing: 8) {
                        Image(systemName: "airplane.departure")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.blue)
                        Text("DEPARTURES")
                            .font(.system(size: 11, weight: .heavy, design: .rounded))
                            .tracking(1.5)
                            .foregroundStyle(.blue.opacity(0.8))
                        Spacer()
                        Text("\(departures.count)")
                            .font(.system(size: 11, weight: .bold, design: .rounded))
                            .foregroundStyle(.blue.opacity(0.5))
                    }
                    .padding(.horizontal, 16).padding(.top, 14).padding(.bottom, 10)
                    
                    // Divider
                    Rectangle().fill(Color.blue.opacity(0.1)).frame(height: 1)
                    
                    // Flight rows
                    ForEach(Array(departures.enumerated()), id: \.element.id) { index, dep in
                        HStack(spacing: 12) {
                            // Flight number
                            Text(dep.safeAwayAbbr)
                                .font(.system(size: 14, weight: .bold, design: .monospaced))
                                .foregroundColor(.white)
                                .frame(width: 80, alignment: .leading)
                            
                            // Route
                            HStack(spacing: 6) {
                                Image(systemName: "mappin.circle.fill")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.blue.opacity(0.6))
                                Image(systemName: "arrow.right")
                                    .font(.system(size: 9, weight: .bold))
                                    .foregroundStyle(.blue.opacity(0.4))
                                Text(dep.safeHomeAbbr)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundColor(.white.opacity(0.6))
                            }
                            
                            Spacer()
                            
                            // Status pill
                            let depDelayed = dep.status.uppercased() == "DELAYED"
                            HStack(spacing: 4) {
                                Circle().fill(depDelayed ? Color.orange : Color.blue).frame(width: 4, height: 4)
                                Text(depDelayed ? "DELAYED" : "OUTBOUND")
                                    .font(.system(size: 8, weight: .heavy, design: .rounded))
                            }
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background((depDelayed ? Color.orange : Color.blue).opacity(0.1))
                            .foregroundColor(depDelayed ? .orange : .blue)
                            .clipShape(Capsule())
                        }
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        
                        if index < departures.count - 1 {
                            Rectangle().fill(Color.white.opacity(0.04)).frame(height: 1).padding(.horizontal, 16)
                        }
                    }
                    
                    Spacer().frame(height: 6)
                }
                .background(Color(white: 0.08))
                .overlay(shape.strokeBorder(Color.blue.opacity(0.12), lineWidth: 1))
                .clipShape(shape)
                .shadow(color: Color.black.opacity(0.1), radius: 8, x: 0, y: 4)
            }
        }
    }
}
// ==========================================
// MARK: - 4. MAIN VIEW
// ==========================================
struct ContentView: View {
    @StateObject var vm = TickerViewModel()
    @State private var selectedTab = 0
    
    init() {
        URLCache.shared = URLCache(memoryCapacity: 512_000, diskCapacity: 1_000_000, diskPath: nil)
        UITabBar.appearance().isHidden = true
    }
    
    var body: some View {
        ZStack(alignment: .bottom) {
            LinearGradient(gradient: Gradient(colors: [Color(red: 0.22, green: 0.28, blue: 0.35), Color(red: 0.05, green: 0.07, blue: 0.10)]), startPoint: .top, endPoint: .bottom).ignoresSafeArea()
            
            TabView(selection: $selectedTab) {
                HomeView(vm: vm).tag(0)
                ModesView(vm: vm).tag(1)
                TeamsView(vm: vm).tag(2)
                SettingsView(vm: vm).tag(3)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .ignoresSafeArea(.container, edges: .bottom)
            
            HStack {
                TabButton(icon: "house.fill", label: "Home", idx: 0, sel: $selectedTab)
                TabButton(icon: "slider.horizontal.3", label: "Modes", idx: 1, sel: $selectedTab)
                TabButton(icon: "tshirt.fill", label: "Teams", idx: 2, sel: $selectedTab)
                TabButton(icon: "cpu", label: "Settings", idx: 3, sel: $selectedTab)
            }
            .padding(12).background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .padding(.horizontal, 20).padding(.bottom, 20)
            .shadow(color: .black.opacity(0.3), radius: 10, x: 0, y: 5)
        }
        .preferredColorScheme(.dark)
        .onOpenURL { vm.handleSpotifyCallback($0) }
    }
}
struct HomeView: View {
    @ObservedObject var vm: TickerViewModel

    private var displayMode: String { vm.state.mode }
    private var sportsFilter: String { vm.state.sports_filter }
    private var leagueLabels: [String: String] { vm.leagueLabels }
    private var splitGames: (
        other: [Game], music: [Game], stocks: [Game], weather: [Game],
        trackedFlights: [Game], airports: [Game]
    ) { partitionedGames }

    private var partitionedGames: (
        other: [Game], music: [Game], stocks: [Game], weather: [Game],
        trackedFlights: [Game], airports: [Game]
    ) {
        var music: [Game] = []
        var stocks: [Game] = []
        var weather: [Game] = []
        var trackedFlights: [Game] = []
        var airports: [Game] = []
        var other: [Game] = []
        for g in vm.games {
            if g.type == "spotify" {
                music.append(g)
            } else if g.type == "stock_ticker" || g.sport == "stock" {
                stocks.append(g)
            } else if g.type == "weather" || g.sport == "weather" {
                weather.append(g)
            } else if g.type == "flight_visitor" {
                trackedFlights.append(g)
            } else if g.type == "flight_airport_hud" || g.sport == "airport" {
                airports.append(g)
            } else {
                other.append(g)
            }
        }
        return (other, music, stocks, weather, trackedFlights, airports)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Ticker Dashboard").font(.system(size: 34, weight: .bold, design: .rounded)).foregroundColor(.white)
                    HStack {
                        Circle().fill(vm.statusColor).frame(width: 8, height: 8)
                        Text(vm.connectionStatus).font(.caption).foregroundColor(.gray)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal).padding(.top, 60)
                
                VStack(alignment: .leading, spacing: 8) {
                    Text("DISPLAY FILTER").font(.caption).bold().foregroundStyle(.secondary)
                    HStack(spacing: 12) {
                        FilterBtn(title: "Show All", val: "all", cur: sportsFilter) { vm.state.sports_filter = "all"; vm.startBurstPolling(); vm.saveSettings() }
                        FilterBtn(title: "Live Only", val: "live", cur: sportsFilter) { vm.state.sports_filter = "live"; vm.startBurstPolling(); vm.saveSettings() }
                        FilterBtn(title: "My Teams", val: "my_teams", cur: sportsFilter) { vm.state.sports_filter = "my_teams"; vm.startBurstPolling(); vm.saveSettings() }
                    }
                    .disabled(!vm.isSportsMode)
                    .opacity(vm.isSportsMode ? 1.0 : 0.4)
                }.padding(.horizontal)
                
                VStack(alignment: .leading, spacing: 12) {
                    Text("ACTIVE FEED").font(.caption).bold().foregroundStyle(.secondary)
                    if vm.games.isEmpty {
                        Text("No active items found.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    } else {
                        ForEach(splitGames.other) { game in
                            GameRow(game: game, leagueLabel: leagueLabels[game.sport], isPinned: vm.isPinned(game))
                                .onTapGesture { vm.togglePin(game) }
                        }
                        ForEach(splitGames.music) { game in
                            MusicNowPlayingCard(game: game)
                        }
                        if displayMode == "stock" {
                            ForEach(splitGames.stocks) { game in
                                StockFeedCard(game: game)
                            }
                        }
                        ForEach(splitGames.weather) { game in
                            WeatherLocationCard(game: game)
                            WeatherCurrentCard(game: game)
                            WeatherTodayCard(game: game)
                        }
                        ForEach(splitGames.trackedFlights) { game in
                            TrackedFlightFeedCard(game: game)
                        }
                        ForEach(splitGames.airports) { game in
                            AirportLocationCard(game: game)
                            AirportScheduleFeedCard(
                                title: "ARRIVALS",
                                icon: "airplane.arrival",
                                flights: game.arrivals ?? [],
                                color: .green
                            )
                            AirportScheduleFeedCard(
                                title: "DEPARTURES",
                                icon: "airplane.departure",
                                flights: game.departures ?? [],
                                color: .orange
                            )
                        }
                    }
                }.padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
    }
}
struct ModeTile: View {
    let title: String
    let icon: String
    let val: String
    let cur: String
    let act: () -> Void
    
    var isSelected: Bool { cur == val }
    
    var body: some View {
        Button(action: act) {
            HStack(spacing: 8) { // Changed to HStack for inline layout
                Image(systemName: icon)
                    .font(.system(size: 16)) // Smaller icon
                Text(title)
                    .font(.subheadline)
                    .bold()
            }
            .frame(maxWidth: .infinity)
            .frame(height: 55) // Reduced height from 85 to 55
            .background(isSelected ? Color.blue : Color.white.opacity(0.05))
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(isSelected ? Color.blue.opacity(0.8) : Color.white.opacity(0.1), lineWidth: 1)
            )
            .foregroundColor(isSelected ? .white : .gray)
            .shadow(color: isSelected ? Color.blue.opacity(0.3) : Color.clear, radius: 4, x: 0, y: 2)
        }
    }
}
struct ModesView: View {
    @ObservedObject var vm: TickerViewModel
    
    // 1. LOCAL BUFFER: This is the secret.
    // The background timer cannot touch this variable.
    @State private var localWeatherInput: String = ""
    @FocusState private var isWeatherFieldFocused: Bool
    
    // Flight tracking local buffers
    @State private var localAirportCode: String = ""
    @State private var localFlightNumber: String = ""
    @State private var localGuestName: String = ""
    @FocusState private var isAirportFieldFocused: Bool
    @FocusState private var isFlightFieldFocused: Bool
    @FocusState private var isGuestFieldFocused: Bool
    
    let modeColumns = [
        GridItem(.flexible(), spacing: 15),
        GridItem(.flexible(), spacing: 15),
        GridItem(.flexible(), spacing: 15)
    ]
    
    var sportsOptions: [LeagueOption] {
        vm.leagueOptions.filter { $0.type == "sport" }
    }
    
    var stockOptions: [LeagueOption] {
        vm.leagueOptions.filter { $0.type == "stock" }
    }
    
    func setCategory(_ target: String) {
        if vm.isSportsOnly && target != "sports" { return }
        if target != "sports" {
            vm.pinnedGameIDs.removeAll()
            vm.state.pinned_games = []
            vm.state.pinned_game = nil
            vm.state.pinned_content_id = ""
            vm.state.sports_presentation = "rotation"
        }
        switch target {
        case "flights":
            // Default Flights to the airport board. Track selects the visitor card.
            if vm.state.mode != "flights" && vm.state.mode != "airports" {
                vm.state.mode = "airports"
                vm.state.flight_submode = "airport"
            }
        case "stock", "weather", "clock", "music":
            vm.state.mode = target
            vm.state.flight_submode = ""
        default:
            vm.state.mode = "sports"
            vm.state.flight_submode = ""
        }
        if target == "stock" {
            let stockKeys = stockOptions.map { $0.id }
            let hasStock = stockKeys.contains { vm.state.active_sports[$0] == true }
            if !hasStock, let first = stockKeys.first {
                vm.state.active_sports[first] = true
            }
        }
        if target == "music" { vm.fetchSpotifyStatus() }
        vm.startBurstPolling()
        vm.saveSettings()
    }
    private func setFlightSubmode(_ submode: String) {
        vm.state.mode = submode == "track" ? "flights" : "airports"
        vm.state.flight_submode = submode
        vm.startBurstPolling()
        vm.saveSettings()
    }
    private func commitFlightNumber() {
        let flight = localFlightNumber.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if flight != vm.state.track_flight_id {
            vm.isEditing = true
            vm.state.track_flight_id = flight
            if flight.isEmpty {
                vm.state.track_guest_name = ""
            }
            vm.saveSettings()
        }
    }
    private func commitGuestName() {
        let guest = localGuestName.trimmingCharacters(in: .whitespacesAndNewlines)
        if guest != vm.state.track_guest_name {
            vm.isEditing = true
            vm.state.track_guest_name = guest
            vm.saveSettings()
        }
    }
    
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack {
                    Text("Modes").font(.system(size: 34, weight: .bold)).foregroundColor(.white)
                    Spacer()
                }
                .padding(.horizontal).padding(.top, 80)
                
                LazyVGrid(columns: modeColumns, spacing: 15) {
                    let utilities = ["stock", "weather", "clock", "music", "flights", "airports"]
                    let displayMode = ["flights", "airports"].contains(vm.state.mode) ? "flights" : vm.state.mode
                    let activeCategory = utilities.contains(displayMode) ? displayMode : "sports"
                    
                    ModeTile(title: "Sports", icon: vm.modeSymbol(for: "sports"), val: "sports", cur: activeCategory) { setCategory("sports") }
                    if !vm.isSportsOnly {
                        ModeTile(title: "Stocks", icon: vm.modeSymbol(for: "stock"), val: "stock", cur: activeCategory) { setCategory("stock") }
                        ModeTile(title: "Music", icon: vm.modeSymbol(for: "music"), val: "music", cur: activeCategory) { setCategory("music") }
                        ModeTile(title: "Flights", icon: vm.modeSymbol(for: "flights"), val: "flights", cur: activeCategory) { setCategory("flights") }
                        ModeTile(title: "Weather", icon: vm.modeSymbol(for: "weather"), val: "weather", cur: activeCategory) { setCategory("weather") }
                        ModeTile(title: "Clock", icon: vm.modeSymbol(for: "clock"), val: "clock", cur: activeCategory) { setCategory("clock") }
                    }
                }
                .padding(.horizontal)
                
                VStack(alignment: .leading, spacing: 20) {
                    if vm.state.mode == "flights" || vm.state.mode == "airports" {
                        VStack(alignment: .leading, spacing: 16) {
                            Text("FLIGHTS MODE").font(.caption).bold().foregroundStyle(.secondary)
                            HStack(spacing: 10) {
                                Button {
                                    setFlightSubmode("airport")
                                } label: {
                                    Text("Airport")
                                        .font(.subheadline).bold()
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 10)
                                        .background(vm.state.mode == "airports" ? Color.blue.opacity(0.8) : Color.white.opacity(0.05))
                                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(vm.state.mode == "airports" ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                                        .foregroundColor(.white)
                                }
                                Button {
                                    setFlightSubmode("track")
                                } label: {
                                    Text("Track")
                                        .font(.subheadline).bold()
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 10)
                                        .background(vm.state.mode == "flights" ? Color.blue.opacity(0.8) : Color.white.opacity(0.05))
                                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(vm.state.mode == "flights" ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                                        .foregroundColor(.white)
                                }
                            }
                            .padding().liquidGlass()
                            if vm.state.mode == "airports" {
                                VStack(alignment: .leading, spacing: 10) {
                                    HStack {
                                        Image(systemName: "building.2.fill").font(.title2).foregroundStyle(.cyan)
                                        VStack(alignment: .leading) {
                                            Text("Airport Activity").bold().foregroundStyle(.white)
                                            if !vm.state.airport_name.isEmpty {
                                                Text(vm.state.airport_name).font(.caption).foregroundStyle(.gray)
                                            }
                                        }
                                        Spacer()
                                    }.padding().liquidGlass()
                                    
                                    HStack {
                                        Text("Airport Code:")
                                        Spacer()
                                        TextField("IATA or ICAO (e.g. EWR, KJFK)", text: $localAirportCode)
                                            .multilineTextAlignment(.trailing)
                                            .foregroundColor(.white)
                                            .autocapitalization(.allCharacters)
                                            .disableAutocorrection(true)
                                            .focused($isAirportFieldFocused)
                                            .onSubmit {
                                                let code = localAirportCode.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
                                                if code.count >= 3 && code.count <= 4 {
                                                    vm.isEditing = true
                                                    vm.state.airport_code_iata = code
                                                    vm.saveSettings()
                                                }
                                                isAirportFieldFocused = false
                                            }
                                    }
                                    .padding().liquidGlass()
                                    if !vm.state.airport_code_iata.isEmpty {
                                        HStack {
                                            Text("Resolved:")
                                                .foregroundStyle(.gray)
                                            Spacer()
                                            Text("\(vm.state.airport_code_iata)  ·  \(vm.state.airport_code_icao)")
                                                .foregroundStyle(.cyan)
                                                .font(.caption)
                                                .monospaced()
                                        }
                                        .padding().liquidGlass()
                                    }
                                }
                            } else {
                                VStack(alignment: .leading, spacing: 10) {
                                    HStack {
                                        Image(systemName: "airplane.circle.fill").font(.title2).foregroundStyle(.orange)
                                        VStack(alignment: .leading) {
                                            Text("Track a Flight").bold().foregroundStyle(.white)
                                            Text("Enter a flight number to track in real time.").font(.caption).foregroundStyle(.gray)
                                        }
                                        Spacer()
                                    }.padding().liquidGlass()
                                    
                                    HStack {
                                        Text("Flight #:")
                                        Spacer()
                                        TextField("e.g. UA123, DAL456", text: $localFlightNumber)
                                            .multilineTextAlignment(.trailing)
                                            .foregroundColor(.white)
                                            .autocapitalization(.allCharacters)
                                            .disableAutocorrection(true)
                                            .focused($isFlightFieldFocused)
                                            .onSubmit {
                                                commitFlightNumber()
                                                isFlightFieldFocused = false
                                            }
                                            .onChange(of: isFlightFieldFocused) { focused in
                                                if !focused { commitFlightNumber() }
                                            }
                                    }
                                    .padding().liquidGlass()
                                    
                                    HStack {
                                        Text("Guest Name:")
                                        Spacer()
                                        TextField("Optional (e.g. Mom)", text: $localGuestName)
                                            .multilineTextAlignment(.trailing)
                                            .foregroundColor(.white)
                                            .focused($isGuestFieldFocused)
                                            .onSubmit {
                                                commitGuestName()
                                                isGuestFieldFocused = false
                                            }
                                            .onChange(of: isGuestFieldFocused) { focused in
                                                if !focused { commitGuestName() }
                                            }
                                    }
                                    .padding().liquidGlass()
                                    
                                    if vm.state.track_flight_id.isEmpty {
                                        HStack(spacing: 10) {
                                            Image(systemName: "airplane.slash")
                                                .font(.title3)
                                                .foregroundStyle(.gray)
                                            VStack(alignment: .leading, spacing: 2) {
                                                Text("No flight selected")
                                                    .font(.subheadline).bold().foregroundStyle(.white)
                                                Text("Enter a flight number above to start tracking.")
                                                    .font(.caption).foregroundStyle(.gray)
                                            }
                                            Spacer()
                                        }
                                        .padding().liquidGlass()
                                    }
                                    if !vm.state.track_flight_id.isEmpty {
                                        HStack {
                                            Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                                            Text("Tracking: \(vm.state.track_flight_id)").bold().foregroundStyle(.white)
                                            Spacer()
                                            Button {
                                                vm.isEditing = true
                                                vm.state.track_flight_id = ""
                                                vm.state.track_guest_name = ""
                                                localFlightNumber = ""
                                                localGuestName = ""
                                                vm.saveSettings()
                                            } label: {
                                                Text("Clear").font(.caption).foregroundStyle(.red)
                                            }
                                        }.padding().liquidGlass()
                                    }
                                }
                            }
                        }
                    } else if vm.state.mode == "weather" {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("WEATHER CONFIGURATION").font(.caption).bold().foregroundStyle(.secondary)
                            HStack {
                                Text("Location:")
                                Spacer()
                                // 2. BIND TO LOCAL INPUT: Not the ViewModel
                                TextField("City or Zip", text: $localWeatherInput)
                                    .multilineTextAlignment(.trailing)
                                    .foregroundColor(.white)
                                    .focused($isWeatherFieldFocused)
                                    .onSubmit {
                                        // 3. PUSH LOCAL TO GLOBAL: Only happens on Enter
                                        vm.weatherLocInput = localWeatherInput
                                        vm.updateWeatherAndSave()
                                        isWeatherFieldFocused = false
                                    }
                            }
                            .padding().liquidGlass()
                        }
                    } else if vm.state.mode == "clock" {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("CLOCK MODE").font(.caption).bold().foregroundStyle(.secondary)
                            Text("Displaying large time and date.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                        }
                    } else if vm.state.mode == "music" {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("NOW PLAYING").font(.caption).bold().foregroundStyle(.secondary)
                            HStack {
                                Image(systemName: "hifispeaker.fill").font(.title2).foregroundStyle(.green)
                                VStack(alignment: .leading) {
                                    Text("Spotify Integration").bold().foregroundStyle(.white)
                                    Text("Ticker will display currently playing track.").font(.caption).foregroundStyle(.gray)
                                }
                                Spacer()
                            }.padding().liquidGlass()
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(vm.spotifyStatus).font(.caption).foregroundStyle(.secondary)
                                    if let accountName = vm.spotifyAccountName {
                                        Text(accountName).font(.caption).foregroundStyle(.gray)
                                    }
                                }
                                Spacer()
                                Button(vm.isConnectingSpotify ? "Connecting..." : "Add account") { vm.connectSpotify() }
                                    .font(.caption).foregroundStyle(.green)
                                    .disabled(vm.isConnectingSpotify)
                            }
                            .padding().liquidGlass()
                            if !vm.spotifyAccounts.isEmpty {
                                VStack(alignment: .leading, spacing: 8) {
                                    Text("CONNECTED ACCOUNTS").font(.caption2).bold().foregroundStyle(.secondary)
                                    ForEach(vm.spotifyAccounts) { account in
                                        HStack(spacing: 10) {
                                            Image(systemName: account.priority ? "star.fill" : "person.crop.circle")
                                                .foregroundStyle(account.priority ? .yellow : .secondary)
                                            VStack(alignment: .leading, spacing: 2) {
                                                Text(account.display_name).font(.subheadline).bold().foregroundStyle(.white)
                                                Text(account.priority ? "Priority account" : "Auto-select when playing")
                                                    .font(.caption2).foregroundStyle(.secondary)
                                            }
                                            Spacer()
                                            Button(account.priority ? "Priority" : "Prioritize") {
                                                vm.setSpotifyPriority(accountID: account.spotify_account_id)
                                            }
                                            .font(.caption).foregroundStyle(account.priority ? .yellow : .green)
                                            Button(role: .destructive) {
                                                vm.disconnectSpotify(accountID: account.spotify_account_id)
                                            } label: {
                                                Image(systemName: "trash")
                                            }
                                            .font(.caption)
                                        }
                                        .padding(10).liquidGlass()
                                    }
                                    if vm.spotifyAccounts.contains(where: { $0.priority }) {
                                        Button("Use whichever account is playing") {
                                            vm.setSpotifyPriority(accountID: nil)
                                        }
                                        .font(.caption).foregroundStyle(.green)
                                    }
                                }
                            }
                            if let error = vm.spotifyError {
                                Text(error).font(.caption).foregroundStyle(.red)
                            }
                        }
                    } else if vm.state.mode == "stock" {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("MARKET SECTORS").font(.caption).bold().foregroundStyle(.secondary)
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140))], spacing: 12) {
                                ForEach(stockOptions) { opt in
                                    let isActive = vm.state.active_sports[opt.id] ?? true
                                    Button {
                                        // 1. CLEAR ALL OTHER STOCKS FIRST
                                        // This forces a "Single Select" behavior
                                        for stockKey in stockOptions.map({ $0.id }) {
                                            vm.state.active_sports[stockKey] = false
                                        }
                                        
                                        // 2. SET THE NEW ONE
                                        vm.state.active_sports[opt.id] = true
                                        
                                        // 3. SAVE
                                        vm.saveSettings()
                                    } label: {
                                        Text(opt.label).font(.subheadline).bold().frame(maxWidth: .infinity).padding(.vertical, 12)
                                            .background(isActive ? Color.blue.opacity(0.8) : Color.white.opacity(0.05))
                                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(isActive ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                                            .foregroundColor(.white)
                                    }
                                }
                            }
                        }
                    } else {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("ENABLED LEAGUES").font(.caption).bold().foregroundStyle(.secondary)
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140))], spacing: 12) {
                                ForEach(sportsOptions) { opt in
                                    let isActive = vm.state.active_sports[opt.id] ?? true
                                    Button {
                                        vm.state.active_sports[opt.id] = !isActive
                                        vm.saveSettings()
                                    } label: {
                                        Text(opt.label).font(.subheadline).bold().frame(maxWidth: .infinity).padding(.vertical, 12)
                                            .background(isActive ? Color.green.opacity(0.8) : Color.white.opacity(0.05))
                                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(isActive ? Color.green : Color.white.opacity(0.1), lineWidth: 1))
                                            .foregroundColor(.white)
                                    }
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
        // 4. SYNC LOGIC: Updates the text field only when NOT typing
        .onAppear {
            localWeatherInput = vm.state.weather_city
            localAirportCode = vm.state.airport_code_iata
            localFlightNumber = vm.state.track_flight_id
            localGuestName = vm.state.track_guest_name
        }
        .onChange(of: vm.state.weather_city) { newValue in
            if !isWeatherFieldFocused {
                localWeatherInput = newValue
            }
        }
        .onChange(of: vm.state.airport_code_iata) { newValue in
            if !isAirportFieldFocused { localAirportCode = newValue }
        }
        .onChange(of: vm.state.track_flight_id) { newValue in
            if !isFlightFieldFocused { localFlightNumber = newValue }
        }
        .onChange(of: vm.state.track_guest_name) { newValue in
            if !isGuestFieldFocused { localGuestName = newValue }
        }
    }
}
struct TeamsView: View {
    @ObservedObject var vm: TickerViewModel
    @State private var selectedLeague = ""
    
    var sportsOptions: [LeagueOption] {
        vm.leagueOptions.filter { opt in
            guard opt.type == "sport" else { return false }
            return opt.my_teams_enabled != false && vm.state.active_sports[opt.id] != false
        }
    }
    
    let teamColumns = [GridItem(.adaptive(minimum: 60))]
    
    var body: some View {
        VStack(spacing: 0) {
            
            // Header
            HStack {
                Text("My Teams").font(.system(size: 34, weight: .bold)).foregroundColor(.white)
                Spacer()
                
                // Status Indicator
                if vm.isEditing {
                    Text("Saving...").font(.caption).bold().foregroundColor(.orange)
                } else {
                    Text("\(vm.state.my_teams.count) Selected").font(.caption).bold().foregroundColor(.gray)
                }
            }
            .padding(.horizontal)
            .padding(.top, 80)
            .padding(.bottom, 10)
            
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    
                    // League Tabs
                    if !sportsOptions.isEmpty {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100))], spacing: 10) {
                            ForEach(sportsOptions) { opt in
                                Button { selectedLeague = opt.id; vm.fetchTeams(for: opt.id) } label: {
                                    Text(opt.label).bold().font(.caption)
                                        .frame(maxWidth: .infinity).padding(.vertical, 8)
                                        .background(selectedLeague == opt.id ? Color.blue : Color(white: 0.2))
                                        .foregroundColor(.white).clipShape(RoundedRectangle(cornerRadius: 8))
                                }
                            }
                        }
                    }
                    
                    Divider().background(Color.white.opacity(0.2))
                    
                    // Teams Grid
                    if let teams = vm.allTeams[selectedLeague], !teams.isEmpty {
                        let filteredTeams = teams
                            .filter { $0.abbr.trimmingCharacters(in: .whitespaces).count > 0 && $0.abbr != "TBD" && $0.abbr != "null" }
                            .sorted { $0.abbr < $1.abbr }
                        
                        LazyVGrid(columns: teamColumns, spacing: 15) {
                            ForEach(filteredTeams, id: \.self) { team in
                                
                                // === SMART MATCHING LOGIC ===
                                // 1. Clean inputs
                                let cleanAbbr = team.abbr.trimmingCharacters(in: .whitespacesAndNewlines)
                                let cleanLeague = selectedLeague.trimmingCharacters(in: .whitespacesAndNewlines)
                                
                                // 2. Construct the "Smart ID" (e.g. nfl:NYG)
                                let smartID = "\(cleanLeague):\(cleanAbbr)"
                                
                                // 3. Check against saved list using scoped ID (e.g. "mlb:ATL")
                                let isSelected = vm.state.my_teams.contains(team.id) ||
                                                 vm.state.my_teams.contains(smartID)
                                
                                Button {
                                    print("🔵 Toggling Team: \(smartID)") // DEBUG PRINT
                                    vm.toggleTeam(smartID)
                                } label: {
                                    VStack {
                                        TeamLogoView(url: team.logo, abbr: team.abbr, size: 40)
                                        Text(team.abbr).font(.caption2).bold()
                                            .foregroundColor(isSelected ? .white : .gray)
                                    }
                                    .padding(8)
                                    .background(isSelected ? Color.blue.opacity(0.3) : Color.clear)
                                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                    .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .stroke(isSelected ? Color.blue : Color.clear, lineWidth: 2))
                                }
                            }
                        }
                    } else if !selectedLeague.isEmpty {
                        Text("No teams found.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    }
                }.padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
        .onAppear {
            if !sportsOptions.isEmpty && (selectedLeague.isEmpty || !sportsOptions.contains(where: { $0.id == selectedLeague })) {
                selectedLeague = sportsOptions.first?.id ?? ""
                vm.fetchTeams(for: selectedLeague)
            }
        }
        .onChange(of: vm.leagueOptions) { _ in
            if !sportsOptions.isEmpty && (selectedLeague.isEmpty || !sportsOptions.contains(where: { $0.id == selectedLeague })) {
                selectedLeague = sportsOptions.first?.id ?? ""
                vm.fetchTeams(for: selectedLeague)
            }
        }
    }
}
struct SettingsView: View {
    @ObservedObject var vm: TickerViewModel
    @State private var showPairing = false
    @State private var rebootConfirm = false
    @State private var showRawJSON = false
    
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack { Text("Settings").font(.system(size: 34, weight: .bold)).foregroundColor(.white); Spacer() }.padding(.horizontal).padding(.top, 80)
                
                VStack(alignment: .leading, spacing: 10) {
                    Text("CONNECTION").font(.caption).bold().foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Server URL").font(.caption).foregroundColor(.gray)
                        TextField("https://...", text: $vm.serverURL).textFieldStyle(.plain).padding(10).background(Color.black.opacity(0.2)).cornerRadius(8).overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1))).foregroundColor(.white)
                            .onSubmit { vm.fetchData(); vm.fetchLeagueOptions(); vm.fetchDevices() }
                    }.padding().liquidGlass()
                }.padding(.horizontal)
                
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text("MY DEVICES").font(.caption).bold().foregroundStyle(.secondary)
                        Spacer()
                        Button(action: { showPairing = true }) {
                            Text("Pair New").font(.caption).bold().foregroundColor(.blue)
                        }
                    }
                    if vm.devices.isEmpty {
                        Text("No devices paired.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    } else {
                        ForEach(vm.devices) { device in
                            DeviceRow(device: device, vm: vm)
                        }
                    }
                }.padding(.horizontal)
                
                if vm.state.show_debug_options == true {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("DEBUG").font(.caption).bold().foregroundStyle(.secondary)
                        VStack(spacing: 0) {
                            Toggle("Debug Mode", isOn: Binding(
                                get: { vm.state.debug_mode },
                                set: { val in
                                    vm.isEditing = true
                                    vm.state.debug_mode = val
                                    vm.sendDebug()
                                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { vm.isEditing = false }
                                }
                            ))
                            .padding()
                            .toggleStyle(SwitchToggleStyle(tint: .orange))
                            
                            Divider().background(Color.white.opacity(0.1))
                            
                            Button("View Raw Server JSON") { showRawJSON = true }
                                .padding()
                                .foregroundColor(.blue)
                            
                        }.liquidGlass().clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }.padding(.horizontal)
                }
                
                VStack(spacing: 12) {
                    Button {
                        if rebootConfirm {
                            vm.reboot()
                            rebootConfirm = false
                        } else {
                            rebootConfirm = true
                            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { rebootConfirm = false }
                        }
                    } label: {
                        Label(rebootConfirm ? "Tap Again to Confirm" : "Reboot Ticker", systemImage: rebootConfirm ? "exclamationmark.triangle.fill" : "power")
                            .frame(maxWidth: .infinity).padding()
                            .background(rebootConfirm ? Color.orange.opacity(0.2) : Color.red.opacity(0.2))
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                            .foregroundColor(rebootConfirm ? .orange : .red)
                            .animation(.easeInOut, value: rebootConfirm)
                    }
                }.padding(.horizontal)
                
                Spacer(minLength: 120)
            }
        }
        .sheet(isPresented: $showPairing) {
            PairingView(vm: vm, isPresented: $showPairing)
        }
        .sheet(isPresented: $showRawJSON) {
            ScrollView { Text(String(describing: vm.games)).font(.caption.monospaced()).padding() }.presentationDetents([.medium])
        }
    }
}
struct DeviceRow: View {
    let device: TickerDevice
    @ObservedObject var vm: TickerViewModel
    
    @State private var brightness: Double
    @State private var speedInt: Double
    @State private var delaySecondsInt: Double
    
    let haptic = UIImpactFeedbackGenerator(style: .medium)
    
    var lastSeenString: String {
        guard let ls = device.last_seen else { return "Never" }
        let diff = Int(Date().timeIntervalSince1970 - ls)
        if diff < 60 { return "Online" }
        if diff < 3600 { return "Last seen: \(diff/60)m ago" }
        return "Last seen: \(diff/3600)h ago"
    }
    
    var isOnline: Bool { return lastSeenString == "Online" }
    
    init(device: TickerDevice, vm: TickerViewModel) {
        self.device = device
        self.vm = vm
        
        // Initialize State from Device Settings
        _brightness = State(initialValue: Double(device.settings.brightness) / 100.0)
        
        let raw = device.settings.scroll_speed
        let uiVal = round((0.11 - raw) * 100)
        _speedInt = State(initialValue: max(1, min(10, uiVal)))
        
        let ds = device.settings.live_delay_seconds ?? 45
        _delaySecondsInt = State(initialValue: Double(ds))
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading) {
                    Text(device.name).font(.headline).foregroundColor(.white)
                    Text("ID: \(device.id.prefix(8))...").font(.caption).foregroundColor(.gray)
                }
                Spacer()
                VStack(alignment: .trailing) {
                    Image(systemName: "light.beacon.max.fill").foregroundColor(isOnline ? .green : .red)
                    Text(lastSeenString).font(.system(size: 9)).foregroundColor(.gray)
                }
            }
            Divider().background(Color.white.opacity(0.1))
            
            // Brightness
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Image(systemName: "sun.max").font(.caption)
                    Spacer()
                    Text("\(Int(brightness * 100))%").font(.caption).monospacedDigit().bold()
                }
                Slider(value: $brightness, in: 0...1, step: 0.05, onEditingChanged: { editing in
                    if !editing { vm.updateDeviceSettings(id: device.id, brightness: brightness) }
                }).tint(.white).onChange(of: brightness) { _ in haptic.impactOccurred() }
            }
            
            // Speed
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Image(systemName: "tortoise").font(.caption)
                    Spacer()
                    Text("Speed: \(Int(speedInt))").font(.caption).monospacedDigit().bold()
                    Spacer()
                    Image(systemName: "hare").font(.caption)
                }
                Slider(value: $speedInt, in: 1...10, step: 1, onEditingChanged: { editing in
                    if !editing {
                        let newFloat = 0.11 - (speedInt * 0.01)
                        vm.updateDeviceSettings(id: device.id, speed: newFloat)
                    }
                }).tint(.blue).onChange(of: speedInt) { _ in haptic.impactOccurred() }
            }
            
            Divider().background(Color.white.opacity(0.1))
            
            HStack {
                Toggle("Inverted", isOn: Binding(
                    get: { device.settings.inverted ?? false },
                    set: { vm.updateDeviceSettings(id: device.id, inverted: $0) }
                )).fixedSize()
                .labelsHidden()
                .toggleStyle(SwitchToggleStyle(tint: .blue))
                Text("Inverted").font(.caption)
                Spacer()
            }
            
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Toggle("Stream Delay", isOn: Binding(
                        get: { device.settings.live_delay_mode ?? false },
                        set: { vm.updateDeviceSettings(id: device.id, liveDelayMode: $0) }
                    ))
                    .labelsHidden()
                    .toggleStyle(SwitchToggleStyle(tint: .orange))
                    
                    Text("Live Stream Delay").font(.caption)
                    Spacer()
                }
                
                if device.settings.live_delay_mode == true {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text("Buffer: \(Int(delaySecondsInt))s")
                                .font(.caption).monospacedDigit().bold().foregroundColor(.orange)
                            Spacer()
                        }
                        Slider(value: $delaySecondsInt, in: 15...120, step: 15, onEditingChanged: { editing in
                            if !editing {
                                vm.updateDeviceSettings(id: device.id, delaySeconds: Int(delaySecondsInt))
                            }
                        })
                        .tint(.orange)
                    }.transition(.opacity)
                }
            }
            
            Divider().background(Color.white.opacity(0.1))
            
            HStack {
                Button(action: { UIPasteboard.general.string = device.id }) { Label("Copy ID", systemImage: "doc.on.doc").font(.caption).bold() }
                Spacer()
                Button(action: { vm.showPairCode(for: device.id) }) { Label("Show Pair Code", systemImage: "number").font(.caption).bold() }
                Spacer()
                Button(action: { vm.unpairTicker(id: device.id) }) { Label("Unpair", systemImage: "trash").font(.caption).bold().foregroundColor(.red) }
            }
        }
        .padding().liquidGlass()
        .alert("Pair Code", isPresented: $vm.showingPairCodeAlert) {
            Button("OK", role: .cancel) { }
        } message: {
            Text(vm.pairCodeAlertMessage)
        }
    }
}
struct PairingView: View {
    @ObservedObject var vm: TickerViewModel
    @Binding var isPresented: Bool
    @State private var pairingMode = 0
    var body: some View {
        NavigationView {
            Form {
                Picker("Method", selection: $pairingMode) { Text("Code").tag(0); Text("Device ID").tag(1) }.pickerStyle(.segmented).padding(.vertical, 8)
                if pairingMode == 0 {
                    Section(header: Text("Instructions")) { Text("1. Ensure your Ticker is powered on."); Text("2. If unpaired, it will display a 6-digit code."); Text("3. Enter that code below.") }
                    Section(header: Text("Device Info")) { TextField("Friendly Name", text: $vm.pairName); TextField("6-Digit Code", text: $vm.pairCode).keyboardType(.numberPad) }
                    Button("Pair with Code") { vm.pairError = nil; vm.pairTicker(code: vm.pairCode, name: vm.pairName.isEmpty ? "My Ticker" : vm.pairName) }.disabled(vm.pairCode.count < 6)
                } else {
                    Section(header: Text("Manual Entry")) { Text("Use this if you know the UUID."); TextField("Friendly Name", text: $vm.pairName); TextField("Device ID (UUID)", text: $vm.pairID) }
                    Button("Pair with ID") { vm.pairError = nil; vm.pairTickerByID(id: vm.pairID, name: vm.pairName.isEmpty ? "My Ticker" : vm.pairName) }.disabled(vm.pairID.count < 4)
                }
                if let err = vm.pairError { Section { Text(err).foregroundColor(.red) } }
            }.navigationTitle("Pair Ticker").navigationBarItems(trailing: Button("Close") { isPresented = false }).alert(isPresented: $vm.showPairSuccess) { Alert(title: Text("Success"), message: Text("Ticker paired successfully!"), dismissButton: .default(Text("OK")) { isPresented = false }) }
        }
    }
}
