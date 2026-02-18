import SwiftUI
import Foundation
import Combine
import UIKit
import CoreLocation

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

// ==========================================
// MARK: - 1. DATA MODELS
// ==========================================

struct LeagueOption: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let label: String
    let type: String
    let enabled: Bool?
}

struct ShootoutData: Decodable, Hashable, Sendable {
    let away: [String]?
    let home: [String]?
}

struct Situation: Decodable, Hashable, Sendable {
    let possession: String?
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
        case possession, downDist, isRedZone, balls, strikes, outs, onFirst, onSecond, onThird, powerPlay, emptyNet, icon, change, shootout
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        if let stringPoss = try? container.decode(String.self, forKey: .possession) { possession = stringPoss }
        else if let intPoss = try? container.decode(Int.self, forKey: .possession) { possession = String(intPoss) }
        else { possession = nil }
        
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
    
    var safeHomeAbbr: String { home_abbr ?? "" }
    var safeAwayAbbr: String { away_abbr ?? "" }
    var safeHomeLogo: String { home_logo ?? "" }
    var safeAwayLogo: String { away_logo ?? "" }
    var safeHomeID: String { home_id ?? safeHomeAbbr }
    var safeAwayID: String { away_id ?? safeAwayAbbr }
    
    enum CodingKeys: String, CodingKey {
        case id, sport, status, state, home_abbr, home_id, home_score, home_logo, home_color, home_alt_color, away_abbr, away_id, away_score, away_logo, away_color, away_alt_color, is_shown, situation, type, tourney_name, guest_name, route, origin_city, dest_city, alt, dist, eta_str, speed, progress, is_live, delay_min, is_delayed
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
}

struct TeamData: Decodable, Identifiable, Hashable, Sendable {
    let id: String // Proper Smart ID (e.g. nfl:NYG)
    let abbr: String
    let logo: String?
}

struct TickerState: Codable, Sendable {
    var active_sports: [String: Bool]
    var mode: String
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
    
    enum CodingKeys: String, CodingKey {
        case active_sports, mode, scroll_seamless, my_teams, debug_mode, custom_date, scroll_speed, show_debug_options, weather_location, weather_city, weather_lat, weather_lon, ticker_id, track_flight_id, track_guest_name, airport_code_iata, airport_code_icao, airport_name, flight_submode
    }
    
    // === 1. ROBUST DECODER ===
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        
        // If server fails to send sports, default to ALL enabled (Safety Net)
        active_sports = (try? container.decode([String: Bool].self, forKey: .active_sports)) ?? TickerState.defaultActiveSports
        
        let rawMode = (try? container.decode(String.self, forKey: .mode)) ?? "all"
        if rawMode == "flight2" {
            mode = "flights"
            flight_submode = "track"
        } else {
            mode = rawMode
            flight_submode = (try? container.decode(String.self, forKey: .flight_submode)) ?? "airport"
        }
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
    }
    
    // === 2. BETTER DEFAULTS (Fixes "NFL Only" bug) ===
    init(active_sports: [String: Bool]? = nil, mode: String = "all", scroll_seamless: Bool = false, my_teams: [String] = [], debug_mode: Bool = false, custom_date: String? = nil, scroll_speed: Double = 5.0, show_debug_options: Bool = false, weather_location: String = "New York", weather_city: String = "New York", weather_lat: Double = 40.7128, weather_lon: Double = -74.0060, ticker_id: String? = nil, track_flight_id: String = "", track_guest_name: String = "", airport_code_iata: String = "EWR", airport_code_icao: String = "KEWR", airport_name: String = "Newark", flight_submode: String = "airport") {
        
        // Default to ALL sports if none provided
        self.active_sports = active_sports ?? TickerState.defaultActiveSports
        
        self.mode = mode
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
    }
    
    // Helper: The "Safety Net" List
    static var defaultActiveSports: [String: Bool] {
        return [
            "nfl": true, "nhl": true, "mlb": true, "nba": true,
            "ncf_fbs": true, "ncf_fcs": true, "ahl": true,
            "soccer_epl": true, "soccer_champ": true, "soccer_champions_league": true,
            "soccer_europa_league": true, "soccer_fa_cup": true, "soccer_l1": true, "soccer_l2": true, "soccer_wc": true,
            "f1": true, "nascar": true, "hockey_olympics": true,
            "weather": true, "clock": true
        ]
    }
}

struct APIResponse: Decodable, Sendable {
    let settings: TickerState
    let games: [Game]
}

struct DeviceSettings: Codable, Sendable {
    var brightness: Int
    var scroll_speed: Double
    var scroll_seamless: Bool?
    var inverted: Bool?
    var live_delay_mode: Bool?
    var live_delay_seconds: Int?
}

struct TickerDevice: Identifiable, Decodable, Sendable {
    let id: String
    let name: String
    var settings: DeviceSettings
    let last_seen: Double?
}

struct PairResponse: Decodable, Sendable {
    let success: Bool
    let message: String?
    let ticker_id: String?
}

// ==========================================
// MARK: - 2. VIEW MODEL
// ==========================================
import SwiftUI
import Foundation
import Combine
import UIKit
import CoreLocation

@MainActor
class TickerViewModel: ObservableObject {
    @Published var games: [Game] = []
    @Published var allTeams: [String: [TeamData]] = [:]
    @Published var leagueOptions: [LeagueOption] = []
    
    // THE SOURCE OF TRUTH
    @Published var state: TickerState = TickerState(
            active_sports: nil, // This will now trigger the "All Sports" default
            mode: "all",
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
    
    // LOCKING MECHANISM (Stops updates while you tap)
    @Published var isEditing: Bool = false
    
    private var isServerReachable = false
    private var timer: Timer?
    private var devicesTimer: Timer?
    private var saveDebounceTimer: Timer?
    private var lastFetchTime: Date = .distantPast
    // After a mode switch, poll every 1s for 30s so the UI and hardware
    // board confirm the new state almost immediately.
    private var burstPollUntil: Date = .distantPast
    
    private var clientID: String {
        if let saved = UserDefaults.standard.string(forKey: "clientID") { return saved }
        let newID = UUID().uuidString
        UserDefaults.standard.set(newID, forKey: "clientID")
        return newID
    }
    
    // PERSISTENT ID TRACKING
    // Remembers your ticker ID so the app doesn't accidentally load empty globals
    private var savedTickerID: String? {
        get { UserDefaults.standard.string(forKey: "latchedTickerID") }
        set { UserDefaults.standard.set(newValue, forKey: "latchedTickerID") }
    }
    
    init() {
        let savedURL = UserDefaults.standard.string(forKey: "serverURL") ?? "https://ticker.mattdicks.org"
        self.serverURL = savedURL
        
        // Initial Data Load
        fetchData()
        fetchLeagueOptions()
        fetchAllTeams()
        fetchDevices()
        
        // Adaptive poll: 1 s during the 30-s burst window after a mode switch,
        // otherwise the normal per-mode interval.
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { _ in
            Task { @MainActor in
                guard !self.isEditing else { return }
                let inBurst = Date() < self.burstPollUntil
                let interval = inBurst ? 1.0 : self.pollInterval(for: self.state.mode)
                if Date().timeIntervalSince(self.lastFetchTime) >= interval {
                    self.lastFetchTime = Date()
                    self.fetchData()
                    if self.leagueOptions.isEmpty { self.fetchLeagueOptions() }
                }
            }
        }

        // Slow poll: device list only changes on pair/unpair
        devicesTimer = Timer.scheduledTimer(withTimeInterval: 30.0, repeats: true) { _ in
            Task { @MainActor in
                if !self.isEditing { self.fetchDevices() }
            }
        }
    }

    private func pollInterval(for mode: String) -> TimeInterval {
        switch mode {
        case "music":                      return 1.0
        case "sports", "live", "my_teams": return 5.0
        case "flights", "flight_tracker":  return 60.0
        case "stocks":                     return 30.0
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
        
        var urlString = "\(base)/api/state"
        if let targetID = self.devices.first?.id ?? self.savedTickerID {
            urlString += "?id=\(targetID)"
        }

        guard let url = URL(string: urlString) else { return }
        
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
                let decoded = try JSONDecoder().decode(APIResponse.self, from: data)
                
                DispatchQueue.main.async {
                    self.isServerReachable = true
                    
                    self.games = decoded.games.sorted { g1, g2 in
                        if g1.type == "stock_ticker" && g2.type != "stock_ticker" { return true }
                        if g1.state == "in" && g2.state != "in" { return true }
                        return false
                    }
                    
                    if !self.isEditing {
                        self.state = decoded.settings
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
        
        // C. DEBOUNCE SAVE (Wait 1.5s after last tap)
        saveDebounceTimer?.invalidate()
        saveDebounceTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: false) { [weak self] _ in
            self?.saveSettings()
        }
    }
    
    // === 3. SAVE SETTINGS (Write) ===
    func saveSettings() {
        self.isEditing = true   // LOCK: block polling while save is in-flight
        let targetID = self.devices.first?.id ?? self.savedTickerID
        
        guard let validID = targetID else { return }
        
        let base = getBaseURL()
        var urlString = "\(base)/api/config"
        urlString += "?id=\(validID)"
        guard let url = URL(string: urlString) else { return }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID") // This matches the Python check
        
        do {
            let data = try JSONEncoder().encode(state)
            var jsonDict = try JSONSerialization.jsonObject(with: data, options: []) as? [String: Any] ?? [:]
            jsonDict["ticker_id"] = validID
            request.httpBody = try JSONSerialization.data(withJSONObject: jsonDict, options: [])
            
            print("📤 Saving settings to \(urlString)")
            URLSession.shared.dataTask(with: request) { data, response, error in
                if let error = error {
                    print("❌ Save failed: \(error.localizedDescription)")
                }
                
                // === NEW SECURITY HANDLING ===
                if let httpResponse = response as? HTTPURLResponse {
                    if httpResponse.statusCode == 403 {
                        DispatchQueue.main.async {
                            print("⛔ Access Denied. Unpairing local app.")
                            // Server rejected us, so we shouldn't be controlling this ticker.
                            self.savedTickerID = nil
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

                // Apply auto-filled airport info immediately from response
                if let data = data,
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    DispatchQueue.main.async {
                        if let iata = json["airport_code_iata"] as? String, !iata.isEmpty {
                            self.state.airport_code_iata = iata
                        }
                        if let icao = json["airport_code_icao"] as? String, !icao.isEmpty {
                            self.state.airport_code_icao = icao
                        }
                        if let name = json["airport_name"] as? String, !name.isEmpty {
                            self.state.airport_name = name
                        }
                    }
                }

                // During a burst poll window (mode just switched) unlock isEditing quickly
                // so the 1-s burst polls can start immediately. Outside burst, keep the
                // 2.5-s delay so team-toggle debounce timers have time to settle.
                let unlockDelay: TimeInterval = Date() < self.burstPollUntil ? 0.3 : 2.5
                DispatchQueue.main.asyncAfter(deadline: .now() + unlockDelay) {
                    if self.saveDebounceTimer?.isValid == true { return }
                    self.isEditing = false
                    self.fetchData()
                }
            }.resume()
        } catch { print("Save Error") }
    }
    
    // --- STANDARD HELPERS ---
    
    func fetchLeagueOptions() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/leagues") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            if let d = data, let decoded = try? JSONDecoder().decode([LeagueOption].self, from: d) {
                DispatchQueue.main.async { self.leagueOptions = decoded }
            }
        }.resume()
    }
    
    func fetchAllTeams() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/teams") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            if let d = data, let decoded = try? JSONDecoder().decode([String: [TeamData]].self, from: d) {
                DispatchQueue.main.async { self.allTeams = decoded }
            }
        }.resume()
    }
    
    func fetchDevices() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/tickers") else { return }
        
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID")
        
        URLSession.shared.dataTask(with: request) { data, _, _ in
            if let d = data, let decoded = try? JSONDecoder().decode([TickerDevice].self, from: d) {
                
                DispatchQueue.main.async {
                    self.devices = decoded
                    
                    // === FIX: AUTO-LOGOUT LOGIC ===
                    // If the server says we have NO paired devices, we must forget the saved ID.
                    if self.devices.isEmpty {
                        if self.savedTickerID != nil {
                            print("🚫 Server reports no paired devices. Clearing latched ID.")
                            self.savedTickerID = nil
                        }
                    }
                    // ==============================
                    
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
            guard let url = URL(string: "\(base)/pair") else {
                self.pairError = "Invalid Server URL"
                return
            }
            
            let body: [String: Any] = ["code": code, "name": name]
            
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            // CRITICAL: Ensure Client ID is sent. This is the key the server uses to "whitelist" the app.
            req.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID")
            
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
                if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode != 200 {
                     DispatchQueue.main.async { self.pairError = "Server Error (Status: \(httpResponse.statusCode))" }
                     return
                }
                
                guard let d = data else {
                    DispatchQueue.main.async { self.pairError = "No data received from server" }
                    return
                }
                
                // Decode Response
                if let res = try? JSONDecoder().decode(PairResponse.self, from: d) {
                    DispatchQueue.main.async {
                        if res.success {
                            self.showPairSuccess = true
                            
                            // 1. Latch onto the new Ticker ID immediately
                            if let newID = res.ticker_id {
                                self.savedTickerID = newID
                                print("✅ Pair Successful. Latching ID: \(newID)")
                            }
                            
                            // 2. Refresh everything
                            self.fetchDevices()
                            self.fetchData()
                            
                        } else {
                            // Show the specific error message from the server if available
                            self.pairError = res.message ?? "Invalid Pairing Code"
                        }
                    }
                } else {
                    DispatchQueue.main.async { self.pairError = "Failed to process server response" }
                }
            }.resume()
        }
    
    func pairTickerByID(id: String, name: String) {
            let base = getBaseURL(); guard let url = URL(string: "\(base)/pair/id") else { return }
            let body: [String: Any] = ["id": id, "name": name]
            var req = URLRequest(url: url); req.httpMethod = "POST"; req.setValue("application/json", forHTTPHeaderField: "Content-Type"); req.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
            URLSession.shared.dataTask(with: req) { data, _, _ in
                 if let d = data, let res = try? JSONDecoder().decode(PairResponse.self, from: d) {
                     DispatchQueue.main.async {
                         if res.success {
                             self.showPairSuccess = true
                             self.savedTickerID = res.ticker_id // 1. Save ID
                             self.fetchDevices()                // 2. Update Status
                             
                             // === FIX: FORCE DATA RELOAD ===
                             print("🔗 Pair successful. Fetching teams for \(res.ticker_id ?? "unknown")...")
                             self.fetchData()                   // 3. GET TEAMS NOW
                             // ==============================
                             
                         } else { self.pairError = res.message }
                     }
                 }
            }.resume()
        }
    
    func unpairTicker(id: String) {
        devices.removeAll { $0.id == id }
        if savedTickerID == id { savedTickerID = nil } // Clear latch
        updateOverallStatus()
        let base = getBaseURL(); guard let url = URL(string: "\(base)/ticker/\(id)/unpair") else { return }
        var req = URLRequest(url: url); req.httpMethod = "POST"; req.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID")
        URLSession.shared.dataTask(with: req).resume()
    }
    
    // ==========================================
    // MARK: - FIX: UPDATE SETTINGS (With Auth & Debugging)
    // ==========================================
    func updateDeviceSettings(id: String, brightness: Double? = nil, speed: Double? = nil, seamless: Bool? = nil, inverted: Bool? = nil, liveDelayMode: Bool? = nil, delaySeconds: Int? = nil) {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/ticker/\(id)") else {
            print("❌ Invalid URL for device update")
            return
        }
        
        var body: [String: Any] = [:]
        
        // Map UI values to Server Keys
        if let b = brightness { body["brightness"] = Int(b * 100) }
        if let s = speed { body["scroll_speed"] = s }
        if let sm = seamless { body["scroll_seamless"] = sm }
        if let inv = inverted { body["inverted"] = inv }
        if let dm = liveDelayMode { body["live_delay_mode"] = dm }
        if let ds = delaySeconds { body["live_delay_seconds"] = ds }
        
        print("📤 Sending Update to \(id): \(body)") // DEBUG LOG
        
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        // CRITICAL: Auth Header
        req.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID")
        
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
                } else {
                    print("⛔ Server Rejected Request. Status: \(httpResponse.statusCode). Did you Pair?")
                }
            }
        }.resume()
    }
    
    // ==========================================
    // MARK: - FIX: REBOOT (With Auth)
    // ==========================================
    func reboot() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/hardware") else { return }
        
        // We set the global flag, so we don't strictly need a specific ID,
        // but passing auth is good practice.
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID")
        
        let body: [String: Any] = ["action": "reboot"]
        
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        
        print("🔌 Sending Reboot Command...")
        URLSession.shared.dataTask(with: req) { _, response, _ in
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 {
                print("✅ Reboot Command Accepted")
            } else {
                print("❌ Reboot Command Failed")
            }
        }.resume()
    }
    
    func sendDebug() {
        let base = getBaseURL(); guard let url = URL(string: "\(base)/api/debug") else { return }
        var req = URLRequest(url: url); req.httpMethod = "POST"; req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = ["debug_mode": state.debug_mode, "custom_date": state.custom_date ?? NSNull()]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req).resume()
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

struct SituationPill: View {
    let text: String; let color: Color
    var body: some View {
        Text(text).font(.system(size: 10, weight: .black)).foregroundColor(color)
            .padding(.horizontal, 6).padding(.vertical, 3).background(color.opacity(0.2))
            .cornerRadius(4).overlay(RoundedRectangle(cornerRadius: 4).stroke(color.opacity(0.3), lineWidth: 1))
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

struct GameRow: View {
    let game: Game
    let leagueLabel: String?
    
    // Drives the continuous animation for the music waveform
    @State private var waveformActive = false

    var activeSituation: String {
        guard let s = game.situation else { return "" }
        if let en = s.emptyNet, en { return "EMPTY NET" }
        if let pp = s.powerPlay, pp { return "PWR PLAY" }
        if let dd = s.downDist { return dd }
        if let rz = s.isRedZone, rz { return "RED ZONE" }
        if let b = s.balls, let str = s.strikes, let o = s.outs { return "\(b)-\(str), \(o) Out" }
        return ""
    }
    
    var situationColor: Color {
        if let s = game.situation {
            if s.isRedZone == true { return Color.red }
            if s.emptyNet == true { return Color.red }
        }
        return Color.yellow
    }
    
    func hasPossession(isHome: Bool) -> Bool {
        guard let s = game.situation, let p = s.possession else { return false }
        let pClean = p.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if pClean.isEmpty { return false }
        let abbr = (isHome ? game.safeHomeAbbr : game.safeAwayAbbr).uppercased()
        let id = (isHome ? game.home_id : game.away_id) ?? ""
        let logo = isHome ? game.safeHomeLogo : game.safeAwayLogo
        if pClean == abbr { return true }
        if pClean == id { return true }
        if logo.contains("/\(pClean).png") || logo.contains("/\(pClean).svg") { return true }
        return false
    }
    
    var isSituationGlobal: Bool {
        guard game.situation != nil else { return false }
        return !activeSituation.isEmpty && !hasPossession(isHome: true) && !hasPossession(isHome: false)
    }
    
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
                Capsule().fill(game.is_shown ? Color.green : Color.red).frame(width: 4, height: 55)
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
                Capsule().fill(game.is_shown ? Color.green : Color.red).frame(width: 4, height: 55)
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
                            else if !activeSituation.isEmpty, hasPossession(isHome: false) { SituationPill(text: activeSituation, color: situationColor) }
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
                            else if !activeSituation.isEmpty, hasPossession(isHome: true) { SituationPill(text: activeSituation, color: situationColor) }
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
    
    private func weatherIcon(for condition: String) -> String {
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
                            HStack(spacing: 4) {
                                Circle().fill(Color.green).frame(width: 4, height: 4)
                                Text("INBOUND")
                                    .font(.system(size: 8, weight: .heavy, design: .rounded))
                            }
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background(Color.green.opacity(0.1))
                            .foregroundColor(.green)
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
                            HStack(spacing: 4) {
                                Circle().fill(Color.blue).frame(width: 4, height: 4)
                                Text("OUTBOUND")
                                    .font(.system(size: 8, weight: .heavy, design: .rounded))
                            }
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background(Color.blue.opacity(0.1))
                            .foregroundColor(.blue)
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
        }.preferredColorScheme(.dark)
    }
}

struct HomeView: View {
    @ObservedObject var vm: TickerViewModel

    private var isSportsMode: Bool {
        let nonSportsModes = ["stocks", "weather", "clock", "music", "flights", "flight_tracker"]
        return !nonSportsModes.contains(vm.state.mode)
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
                        FilterBtn(title: "Show All", val: "sports", cur: vm.state.mode) { vm.state.mode = "sports"; vm.startBurstPolling(); vm.saveSettings() }
                        FilterBtn(title: "Live Only", val: "live", cur: vm.state.mode) { vm.state.mode = "live"; vm.startBurstPolling(); vm.saveSettings() }
                        FilterBtn(title: "My Teams", val: "my_teams", cur: vm.state.mode) { vm.state.mode = "my_teams"; vm.startBurstPolling(); vm.saveSettings() }
                    }
                    .disabled(!isSportsMode)
                    .opacity(isSportsMode ? 1.0 : 0.4)
                }.padding(.horizontal)
                
                VStack(alignment: .leading, spacing: 12) {
                    Text("ACTIVE FEED").font(.caption).bold().foregroundStyle(.secondary)
                    if vm.games.isEmpty {
                        Text("No active items found.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    } else {
                        // Group airport flight items into a board view
                        let airportItems = vm.games.filter { $0.sport == "flight" && ($0.type == "flight_weather" || $0.type == "flight_arrival" || $0.type == "flight_departure") }
                        let otherItems = vm.games.filter { !($0.sport == "flight" && ($0.type == "flight_weather" || $0.type == "flight_arrival" || $0.type == "flight_departure")) }
                        
                        // Render visitor flight cards first (if any)
                        ForEach(otherItems) { game in
                            let label = vm.leagueOptions.first(where: { $0.id == game.sport })?.label
                            GameRow(game: game, leagueLabel: label)
                        }
                        
                        // Render grouped airport board
                        if !airportItems.isEmpty {
                            AirportBoardView(flights: airportItems)
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
    @State private var flightSubMode: Int = 0 // 0 = Airport, 1 = Track Flight
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
        let utilities = ["stocks", "weather", "clock", "music", "flights"]
        if utilities.contains(target) {
            vm.state.mode = target
        } else {
            vm.state.mode = "sports"
        }
        vm.state.active_sports["weather"] = (target == "weather")
        vm.state.active_sports["clock"] = (target == "clock")
        vm.state.active_sports["music"] = (target == "music")
        if target == "flights" {
            // Always reset to airport mode when tapping the Flights category tile.
            // If flight_submode were kept as "track", the server would silently
            // convert mode:"flights" + flight_submode:"track" back to "flight_tracker",
            // requiring a second tap. The sub-mode buttons inside the flights section
            // are the correct place to switch to track mode.
            vm.state.flight_submode = "airport"
            vm.state.active_sports["flight_airport"] = true
            vm.state.active_sports["flight_visitor"] = false
        }
        
        if target == "stocks" {
            let stockKeys = stockOptions.map { $0.id }
            let hasStock = stockKeys.contains { vm.state.active_sports[$0] == true }
            if !hasStock, let first = stockKeys.first {
                vm.state.active_sports[first] = true
            }
        }
        vm.startBurstPolling()
        vm.saveSettings()
    }

    private func setFlightSubmode(_ submode: String) {
        vm.state.flight_submode = submode
        vm.state.active_sports["flight_airport"] = (submode == "airport")
        vm.state.active_sports["flight_visitor"] = (submode == "track")
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
                    let utilities = ["stocks", "weather", "clock", "music", "flights"]
                    // flight_tracker is a sub-variant of flights; show Flights tile as selected.
                    let displayMode = vm.state.mode == "flight_tracker" ? "flights" : vm.state.mode
                    let activeCategory = utilities.contains(displayMode) ? displayMode : "sports"
                    
                    ModeTile(title: "Sports", icon: "sportscourt.fill", val: "sports", cur: activeCategory) { setCategory("sports") }
                    ModeTile(title: "Stocks", icon: "chart.line.uptrend.xyaxis", val: "stocks", cur: activeCategory) { setCategory("stocks") }
                    ModeTile(title: "Music", icon: "music.note", val: "music", cur: activeCategory) { setCategory("music") }
                    ModeTile(title: "Flights", icon: "airplane.arrival", val: "flights", cur: activeCategory) { setCategory("flights") }
                    ModeTile(title: "Weather", icon: "cloud.sun.fill", val: "weather", cur: activeCategory) { setCategory("weather") }
                    ModeTile(title: "Clock", icon: "clock.fill", val: "clock", cur: activeCategory) { setCategory("clock") }
                }
                .padding(.horizontal)
                
                VStack(alignment: .leading, spacing: 20) {
                    if vm.state.mode == "flights" {
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
                                        .background(vm.state.flight_submode == "airport" ? Color.blue.opacity(0.8) : Color.white.opacity(0.05))
                                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(vm.state.flight_submode == "airport" ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                                        .foregroundColor(.white)
                                }
                                Button {
                                    setFlightSubmode("track")
                                } label: {
                                    Text("Track")
                                        .font(.subheadline).bold()
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 10)
                                        .background(vm.state.flight_submode == "track" ? Color.blue.opacity(0.8) : Color.white.opacity(0.05))
                                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(vm.state.flight_submode == "track" ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                                        .foregroundColor(.white)
                                }
                            }
                            .padding().liquidGlass()

                            if vm.state.flight_submode == "airport" {
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
                        }
                    } else if vm.state.mode == "stocks" {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("MARKET SECTORS").font(.caption).bold().foregroundStyle(.secondary)
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140))], spacing: 12) {
                                ForEach(stockOptions) { opt in
                                    let isActive = vm.state.active_sports[opt.id] ?? false
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
                                    let isActive = vm.state.active_sports[opt.id] ?? false
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
            guard vm.state.active_sports[opt.id] == true else { return false }
            if let teams = vm.allTeams[opt.id], !teams.isEmpty { return true }
            return false
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
                                Button { selectedLeague = opt.id } label: {
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
                                
                                // 3. Check against saved list (handle exact match OR smart match)
                                let isSelected = vm.state.my_teams.contains(team.id) ||
                                                 vm.state.my_teams.contains(smartID) ||
                                                 vm.state.my_teams.contains(cleanAbbr)
                                
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
                            .onSubmit { vm.fetchData(); vm.fetchLeagueOptions(); vm.fetchAllTeams(); vm.fetchDevices() }
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
                Button(action: { vm.unpairTicker(id: device.id) }) { Label("Unpair", systemImage: "trash").font(.caption).bold().foregroundColor(.red) }
            }
        }.padding().liquidGlass()
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
