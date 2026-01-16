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
    
    var safeHomeAbbr: String { home_abbr ?? "" }
    var safeAwayAbbr: String { away_abbr ?? "" }
    var safeHomeLogo: String { home_logo ?? "" }
    var safeAwayLogo: String { away_logo ?? "" }
    
    enum CodingKeys: String, CodingKey {
        case id, sport, status, state, home_abbr, home_id, home_score, home_logo, home_color, home_alt_color, away_abbr, away_id, away_score, away_logo, away_color, away_alt_color, is_shown, situation, type, tourney_name
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
    let id: String // <--- FIX: Use the smart ID from server (e.g. "nfl:NYG")
    let abbr: String
    let logo: String?
}

struct TickerState: Codable, Sendable {
    var active_sports: [String: Bool]
    var mode: String
    var scroll_seamless: Bool?
    var my_teams: [String]
    var debug_mode: Bool
    var custom_date: String?
    var scroll_speed: Int?
    var show_debug_options: Bool?
    var weather_location: String?
    var weather_city: String?
    var weather_lat: Double?
    var weather_lon: Double?
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
@MainActor
class TickerViewModel: ObservableObject {
    @Published var games: [Game] = []
    @Published var allTeams: [String: [TeamData]] = [:]
    
    // Dynamic config from server
    @Published var leagueOptions: [LeagueOption] = []
    
    @Published var state: TickerState = TickerState(
        active_sports: ["nfl": true], mode: "all", scroll_seamless: false,
        my_teams: [], debug_mode: false,
        custom_date: nil,
        scroll_speed: 5,
        weather_location: "New York", weather_city: "New York", weather_lat: 40.7128, weather_lon: -74.0060
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
    @Published var isEditing: Bool = false
    
    private var isServerReachable = false
    private var timer: Timer?
    // Add this new timer for the auto-save delay
    private var saveTimer: Timer?
    private var clientID: String {
        if let saved = UserDefaults.standard.string(forKey: "clientID") { return saved }
        let newID = UUID().uuidString
        UserDefaults.standard.set(newID, forKey: "clientID")
        return newID
    }
    
    init() {
        let savedURL = UserDefaults.standard.string(forKey: "serverURL") ?? "https://ticker.mattdicks.org"
        self.serverURL = savedURL
        
        // Initial Fetch
        fetchData()
        fetchLeagueOptions() // Load dynamic leagues
        fetchAllTeams()
        fetchDevices()
        
        timer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { _ in
            Task { @MainActor in
                if !self.isEditing {
                    self.fetchData()
                    self.fetchDevices()
                    if self.leagueOptions.isEmpty { self.fetchLeagueOptions() }
                }
            }
        }
    }
    
    func getBaseURL() -> String {
        return serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: .init(charactersIn: "/"))
    }
    
    func updateOverallStatus() {
        if !isServerReachable { self.connectionStatus = "Server Offline"; self.statusColor = .red; return }
        let now = Date().timeIntervalSince1970
        var activeDeviceFound = false
        if devices.isEmpty { self.connectionStatus = "Server Online (No Ticker)"; self.statusColor = .orange; return }
        for d in devices { if let seen = d.last_seen, (now - seen) < 60 { activeDeviceFound = true } }
        if activeDeviceFound { self.connectionStatus = "Connected • \(self.games.count) Items"; self.statusColor = .green }
        else { self.connectionStatus = "Ticker Offline • \(self.games.count) Items"; self.statusColor = .orange }
    }
    
    func fetchData() {
        let base = getBaseURL()
        if base.isEmpty { self.connectionStatus = "Invalid URL"; self.statusColor = .red; return }
        guard let url = URL(string: "\(base)/api/state") else { self.connectionStatus = "Bad URL"; self.statusColor = .red; return }
        URLSession.shared.dataTask(with: url) { data, _, error in
            if let _ = error { DispatchQueue.main.async { self.isServerReachable = false; self.updateOverallStatus() }; return }
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
                        if let city = decoded.settings.weather_city {
                            self.weatherLocInput = city
                        } else if let loc = decoded.settings.weather_location {
                            self.weatherLocInput = loc
                        }
                    }
                    self.updateOverallStatus()
                }
            } catch { DispatchQueue.main.async { self.isServerReachable = true; self.connectionStatus = "Data Error"; self.statusColor = .red } }
        }.resume()
    }
    
    func fetchLeagueOptions() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/leagues") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            guard let data = data else { return }
            do {
                let decoded = try JSONDecoder().decode([LeagueOption].self, from: data)
                DispatchQueue.main.async {
                    self.leagueOptions = decoded
                }
            } catch { print("Options Decode Error: \(error)") }
        }.resume()
    }
    
    func fetchAllTeams() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/teams") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            guard let data = data else { return }
            do {
                let decoded = try JSONDecoder().decode([String: [TeamData]].self, from: data)
                DispatchQueue.main.async { self.allTeams = decoded }
            } catch { print("Teams Decode Error") }
        }.resume()
    }
    
    func updateWeatherAndSave() {
        let geocoder = CLGeocoder()
        geocoder.geocodeAddressString(weatherLocInput) { placemarks, error in
            DispatchQueue.main.async {
                if let pm = placemarks?.first, let loc = pm.location, let name = pm.locality ?? pm.name {
                    self.state.weather_city = name
                    self.state.weather_lat = loc.coordinate.latitude
                    self.state.weather_lon = loc.coordinate.longitude
                    self.state.weather_location = self.weatherLocInput
                    self.saveSettings()
                } else {
                    self.state.weather_location = self.weatherLocInput
                    self.saveSettings()
                }
            }
        }
    }
    
    func saveSettings() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/config") else { return }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // Ensure backend identifies this client
        request.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID") 
        
        do {
            // 1. Convert State to Dictionary
            let data = try JSONEncoder().encode(state)
            var jsonDict = try JSONSerialization.jsonObject(with: data, options: []) as? [String: Any] ?? [:]

            // THIS IS THE KEY MISSING PIECE IN YOUR APP
            if let activeDeviceID = self.devices.first?.id {
                jsonDict["ticker_id"] = activeDeviceID 
            }
            
            // 2. INJECT TICKER ID (Crucial Fix)
            // We take the ID of the first paired device found in the app.
            if let activeDeviceID = self.devices.first?.id {
                jsonDict["ticker_id"] = activeDeviceID
                print("Saving for Ticker ID: \(activeDeviceID)")
            }
            
            // 3. Send the modified dictionary
            let finalData = try JSONSerialization.data(withJSONObject: jsonDict, options: [])
            request.httpBody = finalData
            
            URLSession.shared.dataTask(with: request) { data, response, error in
                if let error = error { print("Save Error: \(error)"); return }
                if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 {
                    print("✅ Settings Saved Successfully")
                }
            }.resume()
            
        } catch { print("Save Encoding Error: \(error)") }
    }
    
    func fetchDevices() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/tickers") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID")
        URLSession.shared.dataTask(with: request) { data, _, _ in
            guard let data = data else { return }
            do {
                let decoded = try JSONDecoder().decode([TickerDevice].self, from: data)
                DispatchQueue.main.async { self.devices = decoded; self.updateOverallStatus() }
            } catch { print("Devices Decode Error") }
        }.resume()
    }
    
    func pairTicker(code: String, name: String) {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/pair") else { return }
        let body: [String: Any] = ["code": code, "name": name]
        guard let jsonData = try? JSONSerialization.data(withJSONObject: body) else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID")
        request.httpBody = jsonData
        performPairRequest(request: request)
    }
    
    func pairTickerByID(id: String, name: String) {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/pair/id") else { return }
        let body: [String: Any] = ["id": id, "name": name]
        guard let jsonData = try? JSONSerialization.data(withJSONObject: body) else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID")
        request.httpBody = jsonData
        performPairRequest(request: request)
    }
    
    private func performPairRequest(request: URLRequest) {
        URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                if let error = error { self.pairError = "Network Error: \(error.localizedDescription)"; return }
                guard let data = data, let result = try? JSONDecoder().decode(PairResponse.self, from: data) else { self.pairError = "Invalid Response"; return }
                if result.success { self.showPairSuccess = true; self.pairCode = ""; self.pairName = ""; self.pairID = ""; self.fetchDevices() }
                else { self.pairError = result.message ?? "Pairing Failed" }
            }
        }.resume()
    }
    
    func unpairTicker(id: String) {
        devices.removeAll { $0.id == id }
        updateOverallStatus()
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/ticker/\(id)/unpair") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(self.clientID, forHTTPHeaderField: "X-Client-ID")
        URLSession.shared.dataTask(with: request).resume()
    }
    
    func updateDeviceSettings(id: String, brightness: Double? = nil, speed: Double? = nil, seamless: Bool? = nil, inverted: Bool? = nil, delayMode: Bool? = nil, delaySeconds: Int? = nil) {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/ticker/\(id)") else { return }
        var body: [String: Any] = [:]
        if let b = brightness { body["brightness"] = Int(b * 100) }
        if let s = speed { body["scroll_speed"] = s }
        if let sm = seamless { body["scroll_seamless"] = sm }
        if let inv = inverted { body["inverted"] = inv }
        if let dm = delayMode { body["live_delay_mode"] = dm }
        if let ds = delaySeconds { body["live_delay_seconds"] = ds }
        
        guard let jsonData = try? JSONSerialization.data(withJSONObject: body) else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = jsonData
        URLSession.shared.dataTask(with: request).resume()
        
        if let idx = devices.firstIndex(where: { $0.id == id }) {
            if let b = brightness { devices[idx].settings.brightness = Int(b * 100) }
            if let s = speed { devices[idx].settings.scroll_speed = s }
            if let sm = seamless { devices[idx].settings.scroll_seamless = sm }
            if let inv = inverted { devices[idx].settings.inverted = inv }
            if let dm = delayMode { devices[idx].settings.live_delay_mode = dm }
            if let ds = delaySeconds { devices[idx].settings.live_delay_seconds = ds }
        }
    }
    
    func reboot() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/hardware") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["action": "reboot"])
        URLSession.shared.dataTask(with: request).resume()
    }
    
    func sendDebug() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/debug") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = ["debug_mode": state.debug_mode, "custom_date": state.custom_date ?? NSNull()]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: request).resume()
    }
    
    func toggleTeam(_ teamAbbr: String) {
        // 1. Update UI Immediately (Optimistic Update)
        if let index = state.my_teams.firstIndex(of: teamAbbr) {
            state.my_teams.remove(at: index)
        } else {
            state.my_teams.append(teamAbbr)
        }
        
        // 2. Debounce Logic (Wait 1.5s before sending to network)
        print("⏳ Change detected... waiting to save...")
        saveTimer?.invalidate() // Cancel any pending save
        
        saveTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: false) { [weak self] _ in
            print("📤 Triggering Auto-Save now.")
            self?.saveSettings()
        }
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
        
        // --- STOCK TICKER UI ---
        if game.type == "stock_ticker" {
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
            
        // --- LEADERBOARD UI ---
        } else if game.type == "leaderboard" {
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
            
        // --- STANDARD SPORTS UI ---
        } else {
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
// MARK: - 4. MAIN VIEW
// ==========================================
struct ContentView: View {
    @StateObject var vm = TickerViewModel()
    @State private var selectedTab = 0
    init() { UITabBar.appearance().isHidden = true }
    
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
                        FilterBtn(title: "Show All", val: "all", cur: vm.state.mode) { vm.state.mode = "all"; vm.saveSettings() }
                        FilterBtn(title: "Live Only", val: "live", cur: vm.state.mode) { vm.state.mode = "live"; vm.saveSettings() }
                        FilterBtn(title: "My Teams", val: "my_teams", cur: vm.state.mode) { vm.state.mode = "my_teams"; vm.saveSettings() }
                    }
                }.padding(.horizontal)
                
                VStack(alignment: .leading, spacing: 12) {
                    Text("ACTIVE FEED").font(.caption).bold().foregroundStyle(.secondary)
                    if vm.games.isEmpty {
                        Text("No active items found.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    } else {
                        // Pass dynamic label
                        ForEach(vm.games) { game in
                            let label = vm.leagueOptions.first(where: { $0.id == game.sport })?.label
                            GameRow(game: game, leagueLabel: label)
                        }
                    }
                }.padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
    }
}

struct ModesView: View {
    @ObservedObject var vm: TickerViewModel
    var currentMode: String { return vm.state.mode }
    
    var sportsOptions: [LeagueOption] {
        vm.leagueOptions.filter { $0.type == "sport" }
    }
    
    var stockOptions: [LeagueOption] {
        vm.leagueOptions.filter { $0.type == "stock" }
    }
    
    func setMode(_ mode: String) {
        vm.state.mode = mode
        if mode == "stocks" {
            vm.state.active_sports["weather"] = false; vm.state.active_sports["clock"] = false
            let stockKeys = stockOptions.map { $0.id }
            let hasStock = stockKeys.contains { vm.state.active_sports[$0] == true }
            if !hasStock, let first = stockKeys.first { vm.state.active_sports[first] = true }
        } else if mode == "sports" {
            vm.state.active_sports["weather"] = false; vm.state.active_sports["clock"] = false
        } else if mode == "weather" { vm.state.active_sports["weather"] = true
        } else if mode == "clock" { vm.state.active_sports["clock"] = true }
        vm.saveSettings()
    }
    
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack { Text("Modes").font(.system(size: 34, weight: .bold)).foregroundColor(.white); Spacer() }.padding(.horizontal).padding(.top, 80)
                HStack(spacing: 12) {
                    let nonSportsModes = ["stocks", "weather", "clock"]
                    let effectiveMode = nonSportsModes.contains(currentMode) ? currentMode : "sports"
                    
                    FilterBtn(title: "Sports", val: "sports", cur: effectiveMode) { setMode("sports") }
                    FilterBtn(title: "Stocks", val: "stocks", cur: effectiveMode) { setMode("stocks") }
                    FilterBtn(title: "Weather", val: "weather", cur: effectiveMode) { setMode("weather") }
                    FilterBtn(title: "Clock", val: "clock", cur: effectiveMode) { setMode("clock") }
                }.padding(.horizontal)
                
                if currentMode == "weather" {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("WEATHER CONFIGURATION").font(.caption).bold().foregroundStyle(.secondary)
                        HStack {
                            Text("Location:")
                            Spacer()
                            TextField("City or Zip", text: $vm.weatherLocInput)
                                .multilineTextAlignment(.trailing)
                                .foregroundColor(.white)
                                .onSubmit { vm.updateWeatherAndSave() }
                        }.padding().liquidGlass()
                    }.padding(.horizontal)
                } else if currentMode == "clock" {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("CLOCK MODE").font(.caption).bold().foregroundStyle(.secondary)
                        Text("Displaying large time and date.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    }.padding(.horizontal)
                } else if currentMode == "stocks" {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("MARKET SECTORS").font(.caption).bold().foregroundStyle(.secondary)
                        if stockOptions.isEmpty {
                            Text("Loading stock options...").font(.caption).padding().liquidGlass()
                        }
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 140))], spacing: 12) {
                            ForEach(stockOptions) { opt in
                                let isActive = vm.state.active_sports[opt.id] ?? false
                                Button {
                                    vm.state.active_sports[opt.id] = !isActive
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
                    }.padding(.horizontal)
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("ENABLED LEAGUES").font(.caption).bold().foregroundStyle(.secondary)
                        if sportsOptions.isEmpty {
                            Text("Loading sports options...").font(.caption).padding().liquidGlass()
                        }
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 140))], spacing: 12) {
                            ForEach(sportsOptions) { opt in
                                let isActive = vm.state.active_sports[opt.id] ?? false
                                Button { vm.state.active_sports[opt.id] = !isActive; vm.saveSettings() } label: {
                                    Text(opt.label).font(.subheadline).bold().frame(maxWidth: .infinity).padding(.vertical, 12)
                                        .background(isActive ? Color.green.opacity(0.8) : Color.white.opacity(0.05))
                                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(isActive ? Color.green : Color.white.opacity(0.1), lineWidth: 1))
                                        .foregroundColor(.white)
                                }
                            }
                        }
                    }.padding(.horizontal)
                }
                Spacer(minLength: 120)
            }
        }
    }
}

struct TeamsView: View {
    @ObservedObject var vm: TickerViewModel
    @State private var selectedLeague = ""
    
    // Filter out leagues that are disabled OR don't have teams (like F1/NASCAR)
    var sportsOptions: [LeagueOption] {
        vm.leagueOptions.filter { opt in
            guard opt.type == "sport" else { return false }
            guard vm.state.active_sports[opt.id] == true else { return false }
            if let teams = vm.allTeams[opt.id], !teams.isEmpty {
                return true
            }
            return false
        }
    }
    
    let teamColumns = [GridItem(.adaptive(minimum: 60))]
    
    var body: some View {
        VStack(spacing: 0) {
            HStack { Text("My Teams").font(.system(size: 34, weight: .bold)).foregroundColor(.white); Spacer() }.padding(.horizontal).padding(.top, 80).padding(.bottom, 10)
            
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if sportsOptions.isEmpty {
                        if vm.allTeams.isEmpty {
                            Text("Loading teams...").font(.caption).foregroundStyle(.gray).padding()
                        } else {
                            Text("No team sports enabled. Go to Modes to enable NFL, MLB, etc.").font(.caption).foregroundStyle(.gray).padding()
                        }
                    } else {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100))], spacing: 10) {
                            ForEach(sportsOptions) { opt in
                                Button { selectedLeague = opt.id } label: {
                                    Text(opt.label).bold().font(.caption)
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 8)
                                        .background(selectedLeague == opt.id ? Color.blue : Color(white: 0.2))
                                        .foregroundColor(.white)
                                        .clipShape(RoundedRectangle(cornerRadius: 8))
                                }
                            }
                        }
                    }
                    
                    Divider().background(Color.white.opacity(0.2))
                    
                    if let teams = vm.allTeams[selectedLeague], !teams.isEmpty {
                        let filteredTeams = teams
                            .filter { $0.abbr.trimmingCharacters(in: .whitespaces).count > 0 && $0.abbr != "TBD" && $0.abbr != "null" }
                            .sorted { $0.abbr < $1.abbr }
                        
                        LazyVGrid(columns: teamColumns, spacing: 15) {
                            ForEach(filteredTeams, id: \.self) { team in
                                // FIX: Check using the smart ID (team.id) instead of just the abbreviation
                                let isSelected = vm.state.my_teams.contains(team.id)
                                
                                Button { 
                                    vm.isEditing = true; 
                                    // FIX: Toggle the smart ID
                                    vm.toggleTeam(team.id); 
                                    
                                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { vm.isEditing = false } 
                                } label: {
                                    VStack {
                                        TeamLogoView(url: team.logo, abbr: team.abbr, size: 40)
                                        Text(team.abbr).font(.caption2).bold().foregroundColor(isSelected ? .white : .gray)
                                    }
                                    .padding(8).background(isSelected ? Color.blue.opacity(0.3) : Color.clear)
                                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                    .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(isSelected ? Color.blue : Color.clear, lineWidth: 2))
                                }
                            }
                        }
                    } else if !selectedLeague.isEmpty {
                        Text("No teams found for this league.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
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
        .onChange(of: vm.state.active_sports) { _ in
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
            
            // Inverted
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
            
            // === STREAM DELAY (PER TICKER) ===
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Toggle("Stream Delay", isOn: Binding(
                        get: { device.settings.live_delay_mode ?? false },
                        set: { vm.updateDeviceSettings(id: device.id, delayMode: $0) }
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
                    Button("Pair with ID") { vm.pairError = nil; vm.pairTickerByID(id: vm.pairID, name: vm.pairName.isEmpty ? "My Ticker" : vm.pairName) }.disabled(vm.pairID.count < 10)
                }
                if let err = vm.pairError { Section { Text(err).foregroundColor(.red) } }
            }.navigationTitle("Pair Ticker").navigationBarItems(trailing: Button("Close") { isPresented = false }).alert(isPresented: $vm.showPairSuccess) { Alert(title: Text("Success"), message: Text("Ticker paired successfully!"), dismissButton: .default(Text("OK")) { isPresented = false }) }
        }
    }
}
