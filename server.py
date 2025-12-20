import SwiftUI
import Combine

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
        } else {
            possession = nil
        }
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
    let home_abbr: String
    let home_id: String?
    let home_score: String
    let home_logo: String
    let away_abbr: String
    let away_id: String?
    let away_score: String
    let away_logo: String
    let is_shown: Bool
    let situation: Situation?
    
    enum CodingKeys: String, CodingKey {
        case id, sport, status, home_abbr, home_id, home_score, home_logo, away_abbr, away_id, away_score, away_logo, is_shown, situation
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        
        id = try container.decode(String.self, forKey: .id)
        sport = try container.decode(String.self, forKey: .sport)
        status = try container.decode(String.self, forKey: .status)
        home_abbr = try container.decode(String.self, forKey: .home_abbr)
        home_logo = try container.decode(String.self, forKey: .home_logo)
        away_abbr = try container.decode(String.self, forKey: .away_abbr)
        away_logo = try container.decode(String.self, forKey: .away_logo)
        is_shown = try container.decode(Bool.self, forKey: .is_shown)
        situation = try? container.decode(Situation.self, forKey: .situation)
        
        if let hid = try? container.decode(String.self, forKey: .home_id) { home_id = hid }
        else if let hidInt = try? container.decode(Int.self, forKey: .home_id) { home_id = String(hidInt) }
        else { home_id = nil }
        
        if let aid = try? container.decode(String.self, forKey: .away_id) { away_id = aid }
        else if let aidInt = try? container.decode(Int.self, forKey: .away_id) { away_id = String(aidInt) }
        else { away_id = nil }
        
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
    var custom_date: String?
    var weather_location: String?
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
        my_teams: [], debug_mode: false, custom_date: nil, weather_location: "New York"
    )
    
    @Published var serverURL: String { didSet { UserDefaults.standard.set(serverURL, forKey: "serverURL") } }
    @Published var tickerIP: String { didSet { UserDefaults.standard.set(tickerIP, forKey: "tickerIP") } }
    @Published var panelCount: Int { didSet { UserDefaults.standard.set(panelCount, forKey: "panelCount") } }
    @Published var brightness: Double { didSet { UserDefaults.standard.set(brightness, forKey: "brightness") } }
    @Published var inverted: Bool { didSet { UserDefaults.standard.set(inverted, forKey: "inverted") } }
    @Published var weatherLoc: String = "New York"
    
    @Published var connectionStatus: String = "Connecting..."
    @Published var isEditing: Bool = false
    
    private var timer: Timer?

    init() {
        let savedURL = UserDefaults.standard.string(forKey: "serverURL") ?? "https://sportstickerbackend-production.up.railway.app"
        let savedIP = UserDefaults.standard.string(forKey: "tickerIP") ?? "192.168.1.90"
        var savedPanel = UserDefaults.standard.integer(forKey: "panelCount"); if savedPanel == 0 { savedPanel = 2 }
        var savedBright = UserDefaults.standard.double(forKey: "brightness"); if savedBright == 0 { savedBright = 0.5 }
        let savedInv = UserDefaults.standard.bool(forKey: "inverted")

        self.serverURL = savedURL
        self.tickerIP = savedIP
        self.panelCount = savedPanel
        self.brightness = savedBright
        self.inverted = savedInv
        
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
                    self.games = decoded.games
                    if !self.isEditing { 
                        self.state = decoded.settings 
                        self.weatherLoc = decoded.settings.weather_location ?? "New York"
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
                DispatchQueue.main.async { self.allTeams = decoded }
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
        let body: [String: Any] = [
            "brightness": brightness,
            "inverted": inverted,
            "weather_location": weatherLoc
        ]
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
    
    func testPattern() {
        let cleanURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: .init(charactersIn: "/"))
        guard let url = URL(string: "\(cleanURL)/api/hardware") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["action": "test_pattern"])
        URLSession.shared.dataTask(with: request).resume()
    }
    
    func toggleTeam(_ teamAbbr: String, league: String) {
        // Construct namespaced ID
        let teamID = "\(league):\(teamAbbr)"
        
        if let index = state.my_teams.firstIndex(of: teamID) {
            state.my_teams.remove(at: index)
        } else {
            state.my_teams.append(teamID)
        }
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
    let text: String
    let color: Color
    
    var body: some View {
        Text(text)
            .font(.system(size: 10, weight: .black))
            .foregroundColor(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .background(color.opacity(0.2))
            .cornerRadius(4)
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(color.opacity(0.3), lineWidth: 1))
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
                DebugSettingsView(vm: vm).tag(2)
                HardwareSettingsView(vm: vm).tag(3)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .ignoresSafeArea(.container, edges: .bottom)
            
            HStack {
                TabButton(icon: "house.fill", label: "Home", idx: 0, sel: $selectedTab)
                TabButton(icon: "slider.horizontal.3", label: "Modes", idx: 1, sel: $selectedTab)
                TabButton(icon: "ant.fill", label: "Debug", idx: 2, sel: $selectedTab)
                TabButton(icon: "cpu", label: "Ticker", idx: 3, sel: $selectedTab)
            }
            .padding(12).background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 35, style: .continuous))
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
                    HStack { Circle().fill(vm.connectionStatus.contains("Connected") ? Color.green : Color.red).frame(width: 8, height: 8); Text(vm.connectionStatus).font(.caption).foregroundColor(.gray) }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal).padding(.top, 60)
                
                VStack(alignment: .leading, spacing: 8) {
                    Text("DISPLAY FILTER").font(.caption).bold().foregroundStyle(.secondary)
                    HStack(spacing: 12) {
                        FilterBtn(title: "Show All", val: "all", cur: vm.state.mode) { vm.state.mode = "all"; vm.saveSettings() }
                        FilterBtn(title: "Live Only", val: "live", cur: vm.state.mode) { vm.state.mode = "live"; vm.saveSettings() }
                        FilterBtn(title: "My Teams", val: "my_teams", cur: vm.state.mode) { vm.state.mode = "my_teams"; vm.saveSettings() }
                    }
                }.padding(.horizontal)
                
                VStack(alignment: .leading, spacing: 8) {
                    Text("SCROLL STYLE").font(.caption).bold().foregroundStyle(.secondary)
                    HStack(spacing: 12) {
                        ScrollBtn(title: "Paged", val: false, cur: vm.state.scroll_seamless) { vm.state.scroll_seamless = false; vm.saveSettings() }
                        ScrollBtn(title: "Seamless", val: true, cur: vm.state.scroll_seamless) { vm.state.scroll_seamless = true; vm.saveSettings() }
                    }
                }.padding(.horizontal)
                
                VStack(alignment: .leading, spacing: 12) {
                    Text("ACTIVE FEED").font(.caption).bold().foregroundStyle(.secondary)
                    if vm.games.isEmpty { Text("No active games found.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary) }
                    else { ForEach(vm.games) { game in GameRow(game: game) } }
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
    @State private var selectedLeague = "nfl"
    
    var currentMode: String {
        if vm.state.active_sports["weather"] == true { return "weather" }
        if vm.state.active_sports["clock"] == true { return "clock" }
        return "sports"
    }

    let leagues = [("nfl", "NFL"), ("ncf_fbs", "FBS"), ("ncf_fcs", "FCS"), ("mlb", "MLB"), ("nhl", "NHL"), ("nba", "NBA")]
    
    let columns = Array(repeating: GridItem(.flexible(), spacing: 10), count: 5) // FORCE 5 COLUMNS

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
                
                HStack(spacing: 12) {
                    FilterBtn(title: "Sports", val: "sports", cur: currentMode) { setMode("sports") }
                    FilterBtn(title: "Weather", val: "weather", cur: currentMode) { setMode("weather") }
                    FilterBtn(title: "Clock", val: "clock", cur: currentMode) { setMode("clock") }
                }.padding(.horizontal)

                if currentMode == "weather" {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("WEATHER CONFIGURATION").font(.caption).bold().foregroundStyle(.secondary)
                        HStack {
                            Text("Location:")
                            Spacer()
                            TextField("City or Zip", text: $vm.weatherLoc)
                                .multilineTextAlignment(.trailing)
                                .foregroundColor(.white)
                                .onSubmit { vm.saveSettings() }
                        }.padding().liquidGlass()
                    }.padding(.horizontal)
                }

                if currentMode == "clock" {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("CLOCK MODE").font(.caption).bold().foregroundStyle(.secondary)
                        Text("Displaying large 12-hour time and date.")
                            .frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    }.padding(.horizontal)
                }

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
                    
                    VStack(alignment: .leading, spacing: 15) {
                        Text("MANAGE TEAMS").font(.caption).bold().foregroundStyle(.secondary)
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack {
                                ForEach(leagues, id: \.0) { key, name in
                                    Button { selectedLeague = key } label: {
                                        Text(name).bold().padding(.horizontal, 16).padding(.vertical, 8)
                                            .background(selectedLeague == key ? Color.blue : Color.white.opacity(0.1))
                                            .foregroundColor(.white).cornerRadius(20)
                                    }
                                }
                            }
                        }
                        
                        if let teams = vm.allTeams[selectedLeague], !teams.isEmpty {
                            // === DEDUPLICATION LOGIC ===
                            let uniqueTeams = Dictionary(grouping: teams, by: { $0.abbr })
                                .compactMap { $0.value.first } 
                                .filter { !$0.abbr.trimmingCharacters(in: .whitespaces).isEmpty && $0.abbr != "TBD" && $0.abbr != "null" }
                                .sorted { $0.abbr < $1.abbr }
                            
                            LazyVGrid(columns: columns, spacing: 10) {
                                ForEach(uniqueTeams, id: \.id) { team in
                                    // Check NAMESPACED ID
                                    let teamID = "\(selectedLeague):\(team.abbr)"
                                    let isSelected = vm.state.my_teams.contains(teamID)
                                    
                                    Button { 
                                        vm.isEditing = true
                                        vm.toggleTeam(team.abbr, league: selectedLeague)
                                        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { vm.isEditing = false } 
                                    } label: {
                                        // === CARD UI ===
                                        VStack(spacing: 4) {
                                            TeamLogoView(url: team.logo, abbr: team.abbr, size: 30)
                                            Text(team.abbr.trimmingCharacters(in: .whitespaces))
                                                .font(.system(size: 10, weight: .bold))
                                                .lineLimit(1)
                                                .minimumScaleFactor(0.8)
                                                .foregroundColor(isSelected ? .white : .gray)
                                        }
                                        .frame(height: 65)
                                        .frame(maxWidth: .infinity) 
                                        .background(isSelected ? Color.blue.opacity(0.3) : Color.white.opacity(0.05))
                                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                                        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(isSelected ? Color.blue : Color.clear, lineWidth: 2))
                                    }
                                }
                            }.padding(10).liquidGlass()
                        } else { Text("Loading teams...").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary) }
                    }.padding(.horizontal)
                }
                
                Spacer(minLength: 120)
            }
        }
    }
}

// ... (Rest of App file is unchanged) ...
struct DebugSettingsView: View {
    @ObservedObject var vm: TickerViewModel
    @State private var tempDate = Date(); @State private var showRawJSON = false
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack { Text("Debug").font(.system(size: 34, weight: .bold)).foregroundColor(.white); Spacer() }.padding(.horizontal).padding(.top, 80)
                VStack(spacing: 0) {
                    Toggle("Debug Mode", isOn: Binding(get: { vm.state.debug_mode }, set: { vm.state.debug_mode = $0; vm.sendDebug() })).padding().toggleStyle(SwitchToggleStyle(tint: .orange))
                    Divider().background(Color.white.opacity(0.1))
                    Button("View Raw Server JSON") { showRawJSON = true }.padding().foregroundColor(.blue)
                }.liquidGlass().padding(.horizontal)
                VStack(alignment: .leading, spacing: 10) {
                    Text("TIME MACHINE").font(.caption).bold().foregroundStyle(.secondary)
                    VStack(spacing: 0) {
                        DatePicker("Simulate Date", selection: $tempDate, displayedComponents: .date).padding().colorScheme(.dark)
                        HStack(spacing: 0) {
                            Button { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; vm.state.custom_date = f.string(from: tempDate); vm.sendDebug() } label: { Text("Apply Date").frame(maxWidth: .infinity).padding().background(Color.orange.opacity(0.2)).foregroundColor(.orange) }
                            Divider().background(Color.white.opacity(0.1))
                            Button { vm.state.custom_date = nil; vm.sendDebug() } label: { Text("Reset to Live").frame(maxWidth: .infinity).padding().background(Color.white.opacity(0.05)).foregroundColor(.white) }
                        }.frame(height: 50)
                    }.liquidGlass().clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                }.padding(.horizontal)
                Spacer(minLength: 120)
            }.sheet(isPresented: $showRawJSON) { ScrollView { Text(String(describing: vm.games)).font(.caption.monospaced()).padding() }.presentationDetents([.medium]) }
        }
    }
}

struct HardwareSettingsView: View {
    @ObservedObject var vm: TickerViewModel
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack { Text("Ticker").font(.system(size: 34, weight: .bold)).foregroundColor(.white); Spacer() }.padding(.horizontal).padding(.top, 80)
                VStack(alignment: .leading, spacing: 10) {
                    Text("HARDWARE CONFIG").font(.caption).bold().foregroundStyle(.secondary)
                    VStack(spacing: 0) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Server URL").font(.caption).foregroundColor(.gray)
                            TextField("https://...", text: $vm.serverURL).textFieldStyle(.plain).padding(10).background(Color.black.opacity(0.2)).cornerRadius(8).overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1))).foregroundColor(.white)
                                .onSubmit { vm.fetchData(); vm.fetchAllTeams() }
                        }.padding()
                        Divider().background(Color.white.opacity(0.1))
                        
                        Toggle("Inverted (180°)", isOn: Binding(get: { vm.inverted }, set: { vm.inverted = $0; vm.updateHardware() })).padding()
                        Divider().background(Color.white.opacity(0.1))
                        VStack(alignment: .leading) { Text("Brightness: \(Int(vm.brightness * 100))%"); Slider(value: Binding(get: { vm.brightness }, set: { vm.brightness = $0; vm.updateHardware() }), in: 0...1).tint(.green) }.padding()
                    }.liquidGlass().clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                }.padding(.horizontal)
                
                VStack(spacing: 12) {
                    Button { vm.testPattern() } label: { Label("Test LED Pattern", systemImage: "sparkles").frame(maxWidth: .infinity).padding().liquidGlass().foregroundColor(.white) }
                    Button { vm.reboot() } label: { Label("Reboot Ticker", systemImage: "power").frame(maxWidth: .infinity).padding().background(Color.red.opacity(0.2)).clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous)).foregroundColor(.red) }
                }.padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
    }
}

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
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(cur == val ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                .foregroundColor(.white)
        }
    }
}

struct ScrollBtn: View {
    let title: String; let val: Bool; let cur: Bool; let act: () -> Void
    var body: some View {
        Button(action: act) {
            Text(title).font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12)
                .background(cur == val ? Color(red: 0.0, green: 0.47, blue: 1.0) : Color.white.opacity(0.05))
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(cur == val ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                .foregroundColor(.white)
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
        
        let abbr = (isHome ? game.home_abbr : game.away_abbr).uppercased()
        let id = (isHome ? game.home_id : game.away_id) ?? ""
        let logo = isHome ? game.home_logo : game.away_logo
        
        if pClean == abbr { return true }
        if pClean == id { return true }
        if logo.contains("/\(pClean).png") || logo.contains("/\(pClean).svg") { return true }
        
        return false
    }
    
    var isSituationGlobal: Bool {
        guard let s = game.situation else { return false }
        return !activeSituation.isEmpty && !hasPossession(isHome: true) && !hasPossession(isHome: false)
    }
    
    var formattedSport: String {
        switch game.sport { case "ncf_fbs": return "FBS"; case "ncf_fcs": return "FCS"; default: return game.sport.uppercased() }
    }
    
    var body: some View {
        HStack(spacing: 12) {
            Capsule().fill(game.is_shown ? Color.green : Color.red).frame(width: 4, height: 55)
            
            if game.sport == "weather" {
                HStack {
                    Image(systemName: game.situation?.icon == "sun" ? "sun.max.fill" : "cloud.fill").font(.title).foregroundColor(.yellow)
                    VStack(alignment: .leading) {
                        Text(game.away_abbr).font(.headline).bold().foregroundColor(.white)
                        Text(game.status).font(.caption).foregroundColor(.gray)
                    }
                    Spacer()
                    Text(game.home_abbr).font(.system(size: 24, weight: .bold)).foregroundColor(.white)
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
                        TeamLogoView(url: game.away_logo, abbr: game.away_abbr, size: 22)
                        Text(game.away_abbr).font(.headline).bold().foregroundColor(.white)
                        if !activeSituation.isEmpty, hasPossession(isHome: false) { SituationPill(text: activeSituation, color: situationColor) }
                        Spacer(); Text(game.away_score).font(.headline).bold().foregroundColor(.white)
                    }
                    HStack {
                        TeamLogoView(url: game.home_logo, abbr: game.home_abbr, size: 22)
                        Text(game.home_abbr).font(.headline).bold().foregroundColor(.white)
                        if !activeSituation.isEmpty, hasPossession(isHome: true) { SituationPill(text: activeSituation, color: situationColor) }
                        Spacer(); Text(game.home_score).font(.headline).bold().foregroundColor(.white)
                    }
                }
                VStack(alignment: .trailing, spacing: 4) {
                    Text(game.status).font(.caption).bold().padding(.horizontal, 8).padding(.vertical, 4).background(Color.white.opacity(0.1)).cornerRadius(6).foregroundColor(.white)
                    Text(formattedSport).font(.caption2).foregroundStyle(.gray)
                    if isSituationGlobal { SituationPill(text: activeSituation, color: situationColor) }
                }.frame(width: 80, alignment: .trailing)
            }
        }.padding(12).liquidGlass()
    }
}
