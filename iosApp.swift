import SwiftUI
import Foundation
import Combine

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
        case 3: // RGB (12-bit)
            (a, r, g, b) = (255, (int >> 8) * 17, (int >> 4 & 0xF) * 17, (int & 0xF) * 17)
        case 6: // RGB (24-bit)
            (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8: // ARGB (32-bit)
            (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default:
            (a, r, g, b) = (1, 1, 1, 0)
        }
        self.init(
            .sRGB,
            red: Double(r) / 255,
            green: Double(g) / 255,
            blue:  Double(b) / 255,
            opacity: Double(a) / 255
        )
    }
    
    var isGrayscaleOrBlack: Bool {
        guard let components = self.cgColor?.components, components.count >= 3 else { return true }
        let r = components[0], g = components[1], b = components[2]
        let maxC = max(r, max(g, b))
        let minC = min(r, min(g, b))
        let delta = maxC - minC
        let saturation = maxC == 0 ? 0 : delta / maxC
        let brightness = (r * 0.299) + (g * 0.587) + (b * 0.114)
        return brightness < 0.1 || saturation < 0.15
    }
}

// ==========================================
// MARK: - 1. DATA MODELS
// ==========================================

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
    
    enum CodingKeys: String, CodingKey {
        case possession, downDist, isRedZone, balls, strikes, outs, onFirst, onSecond, onThird, powerPlay, emptyNet, icon
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        if let stringPoss = try? container.decode(String.self, forKey: .possession) {
            possession = stringPoss
        } else if let intPoss = try? container.decode(Int.self, forKey: .possession) {
            possession = String(intPoss)
        } else { possession = nil }
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
    }
}

struct Game: Identifiable, Decodable, Hashable, Sendable {
    let id: String
    let sport: String
    let status: String
    let state: String?
    
    // Team Info
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
    let type: String? // 'scoreboard' or 'leaderboard'
    let tourney_name: String? // For Leaderboards
    
    // Derived properties for safe access
    var safeHomeAbbr: String { home_abbr ?? "" }
    var safeAwayAbbr: String { away_abbr ?? "" }
    var safeHomeLogo: String { home_logo ?? "" }
    var safeAwayLogo: String { away_logo ?? "" }
    
    enum CodingKeys: String, CodingKey {
        case id, sport, status, state, home_abbr, home_id, home_score, home_logo, home_color, home_alt_color, away_abbr, away_id, away_score, away_logo, away_color, away_alt_color, is_shown, situation, type, tourney_name
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        sport = try container.decode(String.self, forKey: .sport)
        status = try container.decode(String.self, forKey: .status)
        state = try? container.decode(String.self, forKey: .state)
        
        home_abbr = try? container.decode(String.self, forKey: .home_abbr)
        home_logo = try? container.decode(String.self, forKey: .home_logo)
        home_color = try? container.decode(String.self, forKey: .home_color)
        home_alt_color = try? container.decode(String.self, forKey: .home_alt_color)
        
        away_abbr = try? container.decode(String.self, forKey: .away_abbr)
        away_logo = try? container.decode(String.self, forKey: .away_logo)
        away_color = try? container.decode(String.self, forKey: .away_color)
        away_alt_color = try? container.decode(String.self, forKey: .away_alt_color)
        
        is_shown = try container.decode(Bool.self, forKey: .is_shown)
        situation = try? container.decode(Situation.self, forKey: .situation)
        type = try? container.decode(String.self, forKey: .type)
        tourney_name = try? container.decode(String.self, forKey: .tourney_name)
        
        // Handle IDs (Int or String)
        if let hid = try? container.decode(String.self, forKey: .home_id) { home_id = hid }
        else if let hidInt = try? container.decode(Int.self, forKey: .home_id) { home_id = String(hidInt) }
        else { home_id = nil }
        
        if let aid = try? container.decode(String.self, forKey: .away_id) { away_id = aid }
        else if let aidInt = try? container.decode(Int.self, forKey: .away_id) { away_id = String(aidInt) }
        else { away_id = nil }
        
        // Handle Scores (Int or String)
        if let hs = try? container.decode(String.self, forKey: .home_score) { home_score = hs }
        else if let hsInt = try? container.decode(Int.self, forKey: .home_score) { home_score = String(hsInt) }
        else { home_score = "0" }
        
        if let `as` = try? container.decode(String.self, forKey: .away_score) { away_score = `as` }
        else if let asInt = try? container.decode(Int.self, forKey: .away_score) { away_score = String(asInt) }
        else { away_score = "0" }
    }
}

struct TeamData: Decodable, Identifiable, Hashable, Sendable {
    var id: String { abbr }
    let abbr: String
    let logo: String?
}

struct TickerState: Codable, Sendable {
    var active_sports: [String: Bool]
    var mode: String
    var scroll_seamless: Bool
    var my_teams: [String]
    var debug_mode: Bool
    var demo_mode: Bool?
    var custom_date: String?
    var weather_location: String?
    var scroll_speed: Int?
}

struct APIResponse: Decodable, Sendable {
    let settings: TickerState
    let games: [Game]
}

// ==========================================
// MARK: - 2. VIEW MODEL
// ==========================================

@MainActor
class TickerViewModel: ObservableObject {
    @Published var games: [Game] = []
    @Published var allTeams: [String: [TeamData]] = [:]
    
    @Published var state: TickerState = TickerState(
        active_sports: ["nfl": true], mode: "all", scroll_seamless: false,
        my_teams: [], debug_mode: false, demo_mode: false, custom_date: nil, weather_location: "New York", scroll_speed: 5
    )
    
    @Published var serverURL: String { didSet { UserDefaults.standard.set(serverURL, forKey: "serverURL") } }
    @Published var tickerIP: String { didSet { UserDefaults.standard.set(tickerIP, forKey: "tickerIP") } }
    @Published var panelCount: Int { didSet { UserDefaults.standard.set(panelCount, forKey: "panelCount") } }
    @Published var brightness: Double { didSet { UserDefaults.standard.set(brightness, forKey: "brightness") } }
    @Published var inverted: Bool { didSet { UserDefaults.standard.set(inverted, forKey: "inverted") } }
    @Published var weatherLoc: String = "New York"
    @Published var scrollSpeed: Double = 5.0 { didSet { UserDefaults.standard.set(scrollSpeed, forKey: "scrollSpeed") } }
    
    @Published var connectionStatus: String = "Connecting..."
    @Published var isEditing: Bool = false
    
    // --- STATIC DATA FALLBACK ---
    private let staticTeams: [String: [TeamData]] = [
        "soccer": [
            TeamData(abbr: "ARS", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/359.png"),
            TeamData(abbr: "AVL", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/362.png"),
            TeamData(abbr: "BOU", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/349.png"),
            TeamData(abbr: "BRE", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/337.png"),
            TeamData(abbr: "BHA", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/331.png"),
            TeamData(abbr: "CHE", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/363.png"),
            TeamData(abbr: "CRY", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/384.png"),
            TeamData(abbr: "EVE", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/368.png"),
            TeamData(abbr: "FUL", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/370.png"),
            TeamData(abbr: "IPS", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/365.png"),
            TeamData(abbr: "LEI", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/375.png"),
            TeamData(abbr: "LIV", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/364.png"),
            TeamData(abbr: "MCI", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/382.png"),
            TeamData(abbr: "MUN", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/360.png"),
            TeamData(abbr: "NEW", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/361.png"),
            TeamData(abbr: "NFO", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/393.png"),
            TeamData(abbr: "SOU", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/376.png"),
            TeamData(abbr: "TOT", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/367.png"),
            TeamData(abbr: "WHU", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/371.png"),
            TeamData(abbr: "WOL", logo: "https://a.espncdn.com/i/teamlogos/soccer/500/380.png")
        ]
    ]
    
    private var timer: Timer?
    
    init() {
        let savedURL = UserDefaults.standard.string(forKey: "serverURL") ?? "https://ticker.mattdicks.org"
        let savedIP = UserDefaults.standard.string(forKey: "tickerIP") ?? "192.168.1.90"
        var savedPanel = UserDefaults.standard.integer(forKey: "panelCount"); if savedPanel == 0 { savedPanel = 2 }
        var savedBright = UserDefaults.standard.double(forKey: "brightness"); if savedBright == 0 { savedBright = 0.5 }
        let savedInv = UserDefaults.standard.bool(forKey: "inverted")
        let savedSpeed = UserDefaults.standard.double(forKey: "scrollSpeed");
        
        self.serverURL = savedURL
        self.tickerIP = savedIP
        self.panelCount = savedPanel
        self.brightness = savedBright
        self.inverted = savedInv
        self.scrollSpeed = savedSpeed == 0 ? 5.0 : savedSpeed
        
        self.allTeams = self.staticTeams
        
        fetchData()
        fetchAllTeams()
        
        timer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { _ in
            Task { @MainActor in
                if !self.isEditing { self.fetchData() }
            }
        }
    }
    
    func fetchData() {
        let cleanURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: .init(charactersIn: "/"))
        if cleanURL.isEmpty { self.connectionStatus = "Invalid URL"; return }
        guard let url = URL(string: "\(cleanURL)/api/state") else { self.connectionStatus = "Bad URL"; return }
        
        URLSession.shared.dataTask(with: url) { data, _, error in
            if let _ = error { DispatchQueue.main.async { self.connectionStatus = "Offline" }; return }
            guard let data = data else { return }
            do {
                let decoded = try JSONDecoder().decode(APIResponse.self, from: data)
                DispatchQueue.main.async {
                    self.games = decoded.games.sorted { g1, g2 in
                        if g1.state == "in" && g2.state != "in" { return true }
                        if g1.state != "in" && g2.state == "in" { return false }
                        return false
                    }
                    if !self.isEditing {
                        self.state = decoded.settings
                        self.weatherLoc = decoded.settings.weather_location ?? "New York"
                        if let s = decoded.settings.scroll_speed { self.scrollSpeed = Double(s) }
                    }
                    self.connectionStatus = "Connected • \(self.games.count) Items"
                }
            } catch {
                print("Decode Error: \(error)")
                DispatchQueue.main.async { self.connectionStatus = "Data Error" }
            }
        }.resume()
    }
    
    func fetchAllTeams() {
        let cleanURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: .init(charactersIn: "/"))
        guard let url = URL(string: "\(cleanURL)/api/teams") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            guard let data = data else { return }
            do {
                let decoded = try JSONDecoder().decode([String: [TeamData]].self, from: data)
                DispatchQueue.main.async {
                    self.allTeams = self.staticTeams.merging(decoded) { (_, new) in new }
                }
            } catch { print("Teams Decode Error: \(error)") }
        }.resume()
    }
    
    func saveSettings() {
        let cleanURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: .init(charactersIn: "/"))
        guard let url = URL(string: "\(cleanURL)/api/config") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        do {
            state.weather_location = weatherLoc
            state.scroll_speed = Int(scrollSpeed)
            let body = try JSONEncoder().encode(state)
            request.httpBody = body
            URLSession.shared.dataTask(with: request).resume()
        } catch { print("Save Error: \(error)") }
    }
    
    func sendDebug() {
        let cleanURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: .init(charactersIn: "/"))
        guard let url = URL(string: "\(cleanURL)/api/debug") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = ["debug_mode": state.debug_mode, "custom_date": state.custom_date ?? NSNull()]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: request).resume()
    }
    
    func updateHardware() {
        let cleanURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: .init(charactersIn: "/"))
        guard let url = URL(string: "\(cleanURL)/api/hardware") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = ["brightness": brightness, "inverted": inverted, "weather_location": weatherLoc]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: request).resume()
    }
    
    func reboot() {
        let cleanURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: .init(charactersIn: "/"))
        guard let url = URL(string: "\(cleanURL)/api/hardware") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["action": "reboot"])
        URLSession.shared.dataTask(with: request).resume()
    }
    
    func toggleTeam(_ teamAbbr: String) {
        if let index = state.my_teams.firstIndex(of: teamAbbr) { state.my_teams.remove(at: index) }
        else { state.my_teams.append(teamAbbr) }
        saveSettings()
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

// ==========================================
// MARK: - 5. TAB 1: DASHBOARD
// ==========================================

struct HomeView: View {
    @ObservedObject var vm: TickerViewModel
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Ticker Dashboard").font(.system(size: 34, weight: .bold, design: .rounded)).foregroundColor(.white)
                    HStack {
                        Circle().fill(vm.connectionStatus.contains("Connected") ? Color.green : Color.red).frame(width: 8, height: 8)
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
                        Text("No active games found.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    } else {
                        ForEach(vm.games) { game in GameRow(game: game) }
                    }
                }.padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
    }
}

// ==========================================
// MARK: - 6. TAB 2: MODES
// ==========================================

struct ModesView: View {
    @ObservedObject var vm: TickerViewModel
    
    var currentMode: String {
        if vm.state.active_sports["weather"] == true { return "weather" }
        if vm.state.active_sports["clock"] == true { return "clock" }
        return "sports"
    }
    
    let leagues = [
        ("nfl", "NFL"), ("nba", "NBA"), ("nhl", "NHL"), ("mlb", "MLB"),
        ("ncf_fbs", "NCAA FBS"), ("ncf_fcs", "NCAA FCS"), ("soccer", "Soccer"),
        ("f1", "Formula 1"), ("nascar", "NASCAR"), ("indycar", "IndyCar"),
        ("imsa", "IMSA"), ("wec", "WEC")
    ]
    
    func setMode(_ mode: String) {
        vm.state.active_sports["weather"] = false
        vm.state.active_sports["clock"] = false
        if mode == "weather" { vm.state.active_sports["weather"] = true }
        else if mode == "clock" { vm.state.active_sports["clock"] = true }
        vm.saveSettings()
    }
    
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack { Text("Modes").font(.system(size: 34, weight: .bold)).foregroundColor(.white); Spacer() }.padding(.horizontal).padding(.top, 80)
                
                // --- TOP LEVEL MODE SELECTOR ---
                HStack(spacing: 12) {
                    FilterBtn(title: "Sports", val: "sports", cur: currentMode) { setMode("sports") }
                    FilterBtn(title: "Weather", val: "weather", cur: currentMode) { setMode("weather") }
                    FilterBtn(title: "Clock", val: "clock", cur: currentMode) { setMode("clock") }
                }.padding(.horizontal)
                
                // --- SCROLL STYLE ---
                VStack(alignment: .leading, spacing: 8) {
                    Text("SCROLL STYLE").font(.caption).bold().foregroundStyle(.secondary)
                    HStack(spacing: 12) {
                        ScrollBtn(title: "Paged", val: false, cur: vm.state.scroll_seamless) { vm.state.scroll_seamless = false; vm.saveSettings() }
                        ScrollBtn(title: "Seamless", val: true, cur: vm.state.scroll_seamless) { vm.state.scroll_seamless = true; vm.saveSettings() }
                    }
                }.padding(.horizontal)
                
                // --- WEATHER CONFIG ---
                if currentMode == "weather" {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("WEATHER CONFIGURATION").font(.caption).bold().foregroundStyle(.secondary)
                        HStack {
                            Text("Location:")
                            Spacer()
                            TextField("City or Zip", text: $vm.weatherLoc).multilineTextAlignment(.trailing).foregroundColor(.white).onSubmit { vm.saveSettings() }
                        }.padding().liquidGlass()
                    }.padding(.horizontal)
                }
                
                // --- CLOCK CONFIG ---
                if currentMode == "clock" {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("CLOCK MODE").font(.caption).bold().foregroundStyle(.secondary)
                        Text("Displaying large time and date.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    }.padding(.horizontal)
                }
                
                // --- SPORTS CONFIG ---
                if currentMode == "sports" {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("ENABLED LEAGUES").font(.caption).bold().foregroundStyle(.secondary)
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100))], spacing: 12) {
                            ForEach(leagues, id: \.0) { key, name in
                                let isActive = vm.state.active_sports[key] ?? false
                                Button { vm.state.active_sports[key] = !isActive; vm.saveSettings() } label: {
                                    Text(name).font(.headline).frame(maxWidth: .infinity).padding(.vertical, 14)
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

// ==========================================
// MARK: - 7. TAB 3: TEAMS
// ==========================================

struct TeamsView: View {
    @ObservedObject var vm: TickerViewModel
    @State private var selectedLeague = "nfl"
    
    // UPDATED: Removed Racing leagues. Premier League (soccer) remains.
    let leagues = [
        ("nfl", "NFL"), ("nba", "NBA"), ("nhl", "NHL"), ("mlb", "MLB"),
        ("ncf_fbs", "FBS"), ("ncf_fcs", "FCS"), ("soccer", "Premier League")
    ]
    
    // UPDATED: Used for both league selection and teams
    let gridColumns = [GridItem(.adaptive(minimum: 100), spacing: 10)]
    let teamColumns = [GridItem(.adaptive(minimum: 60))]
    
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack { Text("My Teams").font(.system(size: 34, weight: .bold)).foregroundColor(.white); Spacer() }.padding(.horizontal).padding(.top, 80)
                
                VStack(alignment: .leading, spacing: 15) {
                    Text("MANAGE TEAMS").font(.caption).bold().foregroundStyle(.secondary)
                    
                    // UPDATED: Stacked League Picker (Grid)
                    LazyVGrid(columns: gridColumns, spacing: 10) {
                        ForEach(leagues, id: \.0) { key, name in
                            Button { selectedLeague = key } label: {
                                Text(name).bold().font(.caption)
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 12)
                                    .background(selectedLeague == key ? Color.blue : Color.white.opacity(0.1))
                                    .foregroundColor(.white)
                                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(selectedLeague == key ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                            }
                        }
                    }
                    
                    if let teams = vm.allTeams[selectedLeague], !teams.isEmpty {
                        let filteredTeams = teams
                            .filter { $0.abbr.trimmingCharacters(in: .whitespaces).count > 0 && $0.abbr != "TBD" && $0.abbr != "null" }
                            .sorted { $0.abbr < $1.abbr }
                        
                        LazyVGrid(columns: teamColumns, spacing: 15) {
                            ForEach(filteredTeams, id: \.self) { team in
                                let isSelected = vm.state.my_teams.contains(team.abbr)
                                Button { vm.isEditing = true; vm.toggleTeam(team.abbr); DispatchQueue.main.asyncAfter(deadline: .now() + 2) { vm.isEditing = false } } label: {
                                    VStack {
                                        TeamLogoView(url: team.logo, abbr: team.abbr, size: 40)
                                        Text(team.abbr).font(.caption2).bold().foregroundColor(isSelected ? .white : .gray)
                                    }
                                    .padding(8).background(isSelected ? Color.blue.opacity(0.3) : Color.clear)
                                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                    .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(isSelected ? Color.blue : Color.clear, lineWidth: 2))
                                }
                            }
                        }.padding(10).liquidGlass()
                    } else {
                        Text("Loading teams...").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    }
                }.padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
    }
}

// ==========================================
// MARK: - 8. TAB 4: SETTINGS
// ==========================================

struct SettingsView: View {
    @ObservedObject var vm: TickerViewModel
    @State private var showRawJSON = false
    @State private var rebootConfirm = false
    
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack { Text("Settings").font(.system(size: 34, weight: .bold)).foregroundColor(.white); Spacer() }.padding(.horizontal).padding(.top, 80)
                
                // --- CONNECTION ---
                VStack(alignment: .leading, spacing: 10) {
                    Text("CONNECTION").font(.caption).bold().foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Server URL").font(.caption).foregroundColor(.gray)
                        TextField("https://...", text: $vm.serverURL).textFieldStyle(.plain).padding(10).background(Color.black.opacity(0.2)).cornerRadius(8).overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1))).foregroundColor(.white)
                            .onSubmit { vm.fetchData(); vm.fetchAllTeams() }
                    }.padding().liquidGlass()
                }.padding(.horizontal)
                
                // --- DISPLAY ---
                VStack(alignment: .leading, spacing: 10) {
                    Text("DISPLAY").font(.caption).bold().foregroundStyle(.secondary)
                    VStack(spacing: 0) {
                        Toggle("Inverted (180°)", isOn: Binding(get: { vm.inverted }, set: { vm.inverted = $0; vm.updateHardware() })).padding()
                        Divider().background(Color.white.opacity(0.1))
                        
                        VStack(alignment: .leading) {
                            HStack {
                                Text("Scroll Speed")
                                Spacer()
                                Text("\(Int(vm.scrollSpeed))")
                                    .font(.headline).monospacedDigit().foregroundColor(.white)
                            }
                            Slider(value: Binding(get: { vm.scrollSpeed }, set: { vm.scrollSpeed = $0; vm.saveSettings() }), in: 1...10, step: 1)
                                .tint(.blue)
                        }.padding()
                        
                        Divider().background(Color.white.opacity(0.1))
                        
                        VStack(alignment: .leading) {
                            HStack {
                                Text("Brightness")
                                Spacer()
                                Text("\(Int(vm.brightness * 100))%")
                                    .font(.headline).monospacedDigit().foregroundColor(.white)
                            }
                            Slider(value: Binding(get: { vm.brightness }, set: { vm.brightness = $0; vm.updateHardware() }), in: 0...1, step: 0.05)
                                .tint(.green)
                        }.padding()
                    }.liquidGlass().clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                }.padding(.horizontal)
                
                // --- DEBUG ---
                VStack(alignment: .leading, spacing: 10) {
                    Text("DEBUG").font(.caption).bold().foregroundStyle(.secondary)
                    VStack(spacing: 0) {
                        Toggle("Debug Mode", isOn: Binding(get: { vm.state.debug_mode }, set: { vm.state.debug_mode = $0; vm.sendDebug() })).padding().toggleStyle(SwitchToggleStyle(tint: .orange))
                        Divider().background(Color.white.opacity(0.1))
                        Toggle("Demo Mode", isOn: Binding(get: { vm.state.demo_mode ?? false }, set: { vm.state.demo_mode = $0; vm.saveSettings() })).padding().toggleStyle(SwitchToggleStyle(tint: .purple))
                        Divider().background(Color.white.opacity(0.1))
                        Button("View Raw Server JSON") { showRawJSON = true }.padding().foregroundColor(.blue)
                    }.liquidGlass().clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                }.padding(.horizontal)
                
                // --- REBOOT ---
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
        }.sheet(isPresented: $showRawJSON) { ScrollView { Text(String(describing: vm.games)).font(.caption.monospaced()).padding() }.presentationDetents([.medium]) }
    }
}

// ==========================================
// MARK: - 9. HELPER VIEWS
// ==========================================

struct TabButton: View {
    let icon: String; let label: String; let idx: Int; @Binding var sel: Int
    var body: some View {
        Button { sel = idx } label: {
            VStack(spacing: 4) { Image(systemName: icon).font(.system(size: 20)); Text(label).font(.caption2) }
                .frame(maxWidth: .infinity).foregroundColor(sel == idx ? .white : .gray).padding(.vertical, 8)
                .background(sel == idx ? Color.white.opacity(0.15) : Color.clear).cornerRadius(12)
        }
    }
}

struct FilterBtn: View {
    let title: String; let val: String; let cur: String; let act: () -> Void
    var body: some View {
        Button(action: act) {
            Text(title).font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12)
                .background(cur == val ? Color(red: 0.0, green: 0.47, blue: 1.0) : Color.white.opacity(0.05))
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous)).overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(cur == val ? Color.blue : Color.white.opacity(0.1), lineWidth: 1)).foregroundColor(.white)
        }
    }
}

struct ScrollBtn: View {
    let title: String; let val: Bool; let cur: Bool; let act: () -> Void
    var body: some View {
        Button(action: act) {
            Text(title).font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12)
                .background(cur == val ? Color(red: 0.0, green: 0.47, blue: 1.0) : Color.white.opacity(0.05))
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous)).overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(cur == val ? Color.blue : Color.white.opacity(0.1), lineWidth: 1)).foregroundColor(.white)
        }
    }
}

struct TeamLogoView: View {
    let url: String?; let abbr: String; let size: CGFloat
    var body: some View {
        AsyncImage(url: URL(string: url ?? "")) { phase in
            if let image = phase.image { image.resizable().scaledToFit() }
            else { ZStack { Circle().fill(Color.gray.opacity(0.3)); Text(abbr).font(.system(size: size * 0.35, weight: .bold)).foregroundColor(.white.opacity(0.8)) } }
        }.frame(width: size, height: size)
    }
}

// ==========================================
// MARK: - 10. GAME ROW
// ==========================================

struct GameRow: View {
    let game: Game
    
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
        switch game.sport { case "ncf_fbs": return "FBS"; case "ncf_fcs": return "FCS"; default: return game.sport.uppercased() }
    }
    
    var isLive: Bool { return game.state == "in" }

    func prioritizeVibrantColor(primary: String?, alternate: String?) -> Color {
        let pColor = Color(hex: primary ?? "#000000")
        let aColor = Color(hex: alternate ?? "#000000")
        if pColor.isGrayscaleOrBlack && !aColor.isGrayscaleOrBlack { return aColor }
        return pColor
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)
        
        if game.type == "leaderboard" {
            HStack(spacing: 12) {
                Capsule().fill(game.is_shown ? Color.green : Color.red).frame(width: 4, height: 55)
                VStack(alignment: .leading) {
                    Text(game.tourney_name ?? "Event").font(.headline).bold().foregroundColor(.white)
                    Text(game.status).font(.caption).foregroundColor(.gray)
                }
                Spacer()
                Text(game.sport.uppercased()).font(.system(size: 14, weight: .bold)).foregroundColor(.white).padding(6).background(Color.white.opacity(0.1)).cornerRadius(6)
            }
            .padding(12).background(Color(white: 0.15))
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)
        }
        else {
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
                            if !activeSituation.isEmpty, hasPossession(isHome: false) { SituationPill(text: activeSituation, color: situationColor) }
                            Spacer(); Text(game.away_score).font(.headline).bold().foregroundColor(.white)
                        }
                        HStack {
                            TeamLogoView(url: game.safeHomeLogo, abbr: game.safeHomeAbbr, size: 22)
                            Text(game.safeHomeAbbr).font(.headline).bold().foregroundColor(.white)
                            if !activeSituation.isEmpty, hasPossession(isHome: true) { SituationPill(text: activeSituation, color: situationColor) }
                            Spacer(); Text(game.home_score).font(.headline).bold().foregroundColor(.white)
                        }
                    }
                    VStack(alignment: .trailing, spacing: 4) {
                        Text(game.status)
                            .font(.caption).bold().padding(.horizontal, 8).padding(.vertical, 4)
                            .background(isLive ? Color.red.opacity(0.1) : Color.white.opacity(0.1))
                            .cornerRadius(6).foregroundColor(.white)
                        Text(formattedSport).font(.caption2).foregroundStyle(.gray)
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
