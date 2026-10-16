import SwiftUI
import Foundation
import Combine
import UIKit
import CoreLocation
import Security
import AuthenticationServices
import NetworkExtension
import CoreBluetooth
import CryptoKit

@MainActor
class TickerViewModel: NSObject, ObservableObject, ASWebAuthenticationPresentationContextProviding, CLLocationManagerDelegate {
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
    var needsInitialSetup: Bool {
        savedTickerID == nil
    }
    var activeTicker: TickerDevice? {
        guard let activeID = savedTickerID else { return nil }
        return devices.first(where: { $0.id == activeID })
    }
    var activeTickerIndicator: String {
        guard let ticker = activeTicker else { return "Choose a ticker" }
        let family = ticker.profile?.product_family.uppercased() ?? "TICKER"
        let index = devices.firstIndex(where: { $0.id == ticker.id }).map { "\($0 + 1)/\(max(1, devices.count))" } ?? ""
        return [ticker.name, family, index].filter { !$0.isEmpty }.joined(separator: " • ")
    }
    var pairedTickerCount: Int { devices.count }
    var canShareTickerGroup: Bool { controllerGroupID != nil && controllerGroupSecret() != nil }

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
    @Published var pairError: String?
    @Published var showPairSuccess: Bool = false
    @Published var serverURL: String { didSet { UserDefaults.standard.set(serverURL, forKey: "serverURL") } }
    @Published var weatherLocInput: String = "New York"
    @Published var connectionStatus: String = "Connecting..."
    @Published var statusColor: Color = .gray
    @Published var scheduleActive: Bool = false
    @Published var spotifyStatus: String = "Checking Spotify..."
    @Published var spotifyAccountName: String?
    @Published var spotifyAccounts: [SpotifyAccount] = []
    @Published var spotifyError: String?
    @Published var isConnectingSpotify = false
    @Published var pairCodeAlertMessage = ""
    @Published var showingPairCodeAlert = false
    @Published var wifiSetupCode: String = ""
    @Published var wifiHomeSSID: String = ""
    @Published var wifiHomePassword: String = ""
    @Published var wifiSetupStatus: String = ""
    @Published var wifiSetupError: String?
    @Published var isWifiSetupInProgress = false
    @Published var wifiNetworkChoice = 0
    @Published var wifiDetectedSSID = ""

    // LOCKING MECHANISM (Stops updates while you tap)
    @Published var isEditing: Bool = false

    private var isServerReachable = false
    private var timer: Timer?
    private var devicesTimer: Timer?
    private var saveDebounceTimer: Timer?
    private var currentSaveTask: URLSessionDataTask?
    private var deviceListTask: URLSessionDataTask?
    private var deviceListGate = DeviceListRequestGate()
    private var selection: DeviceSelectionReducer
    private var spotifyAuthorizationSession: ASWebAuthenticationSession?
    private var wifiLocationManager: CLLocationManager?
    private let bleProvisioning = BLEProvisioningCoordinator()
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

    private var controllerGroupID: String? {
        get { UserDefaults.standard.string(forKey: "controllerGroupID") }
        set { UserDefaults.standard.set(newValue, forKey: "controllerGroupID") }
    }

    private var sharedMyTeams: [String]? {
        get { UserDefaults.standard.array(forKey: "sharedMyTeams") as? [String] }
        set { UserDefaults.standard.set(newValue, forKey: "sharedMyTeams") }
    }

    private func selectActiveTicker(_ tickerID: String?) {
        selection.select(tickerID)
        savedTickerID = tickerID
    }

    func switchToTicker(_ tickerID: String) {
        guard devices.contains(where: { $0.id == tickerID }), tickerID != savedTickerID else { return }
        selectActiveTicker(tickerID)
        games.removeAll()
        leagueOptions.removeAll()
        modeSymbols.removeAll()
        scheduleActive = false
        isServerReachable = false
        fetchData()
        fetchLeagueOptions()
        fetchModeOptions()
        fetchSpotifyStatus()
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

    private func controllerGroupSecret() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "matt.TickerControl.controller-group-secret",
            kSecAttrAccount as String: getBaseURL(),
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    @discardableResult
    private func saveControllerGroup(id: String, secret: String) -> Bool {
        controllerGroupID = id
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "matt.TickerControl.controller-group-secret",
            kSecAttrAccount as String: getBaseURL(),
        ]
        let attributes: [String: Any] = [kSecValueData as String: Data(secret.utf8)]
        let updateStatus = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updateStatus == errSecSuccess { return true }
        guard updateStatus == errSecItemNotFound else { return false }
        var addQuery = query
        addQuery[kSecValueData as String] = Data(secret.utf8)
        return SecItemAdd(addQuery as CFDictionary, nil) == errSecSuccess
    }

    @discardableResult
    private func saveControllerToken(_ token: String, for tickerID: String) -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "matt.TickerControl.controller-token",
            kSecAttrAccount as String: tickerID,
        ]
        let attributes: [String: Any] = [kSecValueData as String: Data(token.utf8)]
        let updateStatus = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updateStatus == errSecSuccess { return true }
        guard updateStatus == errSecItemNotFound else { return false }

        var addQuery = query
        addQuery[kSecValueData as String] = Data(token.utf8)
        return SecItemAdd(addQuery as CFDictionary, nil) == errSecSuccess
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
        guard let identifier else { return nil }
        // A group session can authorize every ticker in the same app group.
        let token = controllerToken(for: identifier)
            ?? (controllerGroupID != nil ? savedTickerID.flatMap { controllerToken(for: $0) } : nil)
        guard let token else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        return request
    }

    private func scheduleRequest<T: Decodable>(
        tickerID: String,
        suffix: String,
        method: String,
        body: [String: Any]? = nil,
        decode: T.Type,
        completion: @escaping (Result<T, Error>) -> Void
    ) {
        guard let url = tickerURL(tickerID, suffix: suffix),
              var request = authorizedRequest(url: url, method: method, tickerID: tickerID) else {
            completion(.failure(TickerScheduleRequestError.authorization))
            return
        }
        if let body {
            do {
                request.httpBody = try JSONSerialization.data(withJSONObject: body)
            } catch {
                completion(.failure(error))
                return
            }
        }
        URLSession.shared.dataTask(with: request) { data, response, error in
            let result: Result<T, Error>
            if let error {
                result = .failure(error)
            } else if let httpResponse = response as? HTTPURLResponse,
                      !(200...299).contains(httpResponse.statusCode) {
                result = .failure(TickerScheduleRequestError.server("Schedule request failed (HTTP \(httpResponse.statusCode))."))
            } else if let data {
                do {
                    result = .success(try JSONDecoder().decode(T.self, from: data))
                } catch {
                    result = .failure(error)
                }
            } else {
                result = .failure(TickerScheduleRequestError.invalidResponse)
            }
            DispatchQueue.main.async {
                completion(result)
            }
        }.resume()
    }

    private func scheduleMutation(
        tickerID: String,
        suffix: String,
        method: String,
        body: [String: Any]? = nil,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        scheduleRequest(
            tickerID: tickerID,
            suffix: suffix,
            method: method,
            body: body,
            decode: TickerScheduleMutationResponse.self
        ) { result in
            completion(result.map { _ in () })
        }
    }

    func fetchSchedule(
        for tickerID: String,
        completion: @escaping (Result<TickerScheduleResponse, Error>) -> Void
    ) {
        scheduleRequest(
            tickerID: tickerID,
            suffix: "/schedule",
            method: "GET",
            decode: TickerScheduleResponse.self,
            completion: completion
        )
    }

    func createScheduleBlock(
        tickerID: String,
        daysOfWeek: [Int],
        startMinute: Int,
        endMinute: Int,
        mode: String,
        sportsFilter: String?,
        enabled: Bool = true,
        completion: @escaping (Result<TickerScheduleBlock, Error>) -> Void
    ) {
        var body: [String: Any] = [
            "days_of_week": daysOfWeek,
            "start_minute": startMinute,
            "end_minute": endMinute,
            "mode": mode,
            "enabled": enabled,
        ]
        body["sports_filter"] = sportsFilter ?? NSNull()
        scheduleRequest(
            tickerID: tickerID,
            suffix: "/schedule/blocks",
            method: "POST",
            body: body,
            decode: TickerScheduleBlock.self,
            completion: completion
        )
    }

    func updateScheduleBlock(
        tickerID: String,
        blockID: String,
        daysOfWeek: [Int],
        startMinute: Int,
        endMinute: Int,
        mode: String,
        sportsFilter: String?,
        enabled: Bool,
        completion: @escaping (Result<TickerScheduleBlock, Error>) -> Void
    ) {
        var body: [String: Any] = [
            "days_of_week": daysOfWeek,
            "start_minute": startMinute,
            "end_minute": endMinute,
            "mode": mode,
            "enabled": enabled,
        ]
        body["sports_filter"] = sportsFilter ?? NSNull()
        scheduleRequest(
            tickerID: tickerID,
            suffix: "/schedule/blocks/\(blockID)",
            method: "PATCH",
            body: body,
            decode: TickerScheduleBlock.self,
            completion: completion
        )
    }

    func deleteScheduleBlock(
        tickerID: String,
        blockID: String,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        scheduleMutation(
            tickerID: tickerID,
            suffix: "/schedule/blocks/\(blockID)",
            method: "DELETE",
            completion: completion
        )
    }

    func createScheduleCondition(
        tickerID: String,
        threshold: Int,
        `operator` conditionOperator: String,
        enabled: Bool = true,
        completion: @escaping (Result<TickerScheduleCondition, Error>) -> Void
    ) {
        let body: [String: Any] = [
            "kind": "live_games",
            "threshold": threshold,
            "operator": conditionOperator,
            "when_mode": "sports",
            "action_sports_filter": "live",
            "ignore_pinned": true,
            "enabled": enabled,
        ]
        scheduleRequest(
            tickerID: tickerID,
            suffix: "/schedule/conditions",
            method: "POST",
            body: body,
            decode: TickerScheduleCondition.self,
            completion: completion
        )
    }

    func updateScheduleCondition(
        tickerID: String,
        conditionID: String,
        threshold: Int,
        `operator` conditionOperator: String,
        enabled: Bool,
        completion: @escaping (Result<TickerScheduleCondition, Error>) -> Void
    ) {
        let body: [String: Any] = [
            "threshold": threshold,
            "operator": conditionOperator,
            "when_mode": "sports",
            "action_sports_filter": "live",
            "ignore_pinned": true,
            "enabled": enabled,
        ]
        scheduleRequest(
            tickerID: tickerID,
            suffix: "/schedule/conditions/\(conditionID)",
            method: "PATCH",
            body: body,
            decode: TickerScheduleCondition.self,
            completion: completion
        )
    }

    func deleteScheduleCondition(
        tickerID: String,
        conditionID: String,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        scheduleMutation(
            tickerID: tickerID,
            suffix: "/schedule/conditions/\(conditionID)",
            method: "DELETE",
            completion: completion
        )
    }

    func setScheduleOverride(
        tickerID: String,
        enabled: Bool,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        scheduleMutation(
            tickerID: tickerID,
            suffix: "",
            method: "PATCH",
            body: ["schedule_override": enabled],
            completion: completion
        )
    }

    override init() {
        let savedURL = UserDefaults.standard.string(forKey: "serverURL") ?? "https://ticker.mattdicks.org"
        self.serverURL = savedURL
        self.selection = DeviceSelectionReducer(activeTickerID: UserDefaults.standard.string(forKey: "latchedTickerID"))
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

    func fetchCurrentWiFiSSID() {
        guard CLLocationManager.locationServicesEnabled() else {
            wifiSetupError = "Location Services must be enabled to detect the current Wi-Fi name."
            return
        }
        if wifiLocationManager == nil {
            let manager = CLLocationManager()
            manager.delegate = self
            wifiLocationManager = manager
        }
        guard let manager = wifiLocationManager else { return }
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse:
            readCurrentWiFiSSID()
        case .notDetermined:
            manager.requestWhenInUseAuthorization()
        default:
            wifiSetupError = "Allow location access to detect the current Wi-Fi name, or choose Different Wi-Fi."
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        if manager.authorizationStatus == .authorizedAlways || manager.authorizationStatus == .authorizedWhenInUse {
            readCurrentWiFiSSID()
        }
    }

    private func readCurrentWiFiSSID() {
        NEHotspotNetwork.fetchCurrent { network in
            DispatchQueue.main.async {
                guard let ssid = network?.ssid, !ssid.isEmpty else {
                    self.wifiSetupError = "iOS could not identify the current Wi-Fi. Choose Different Wi-Fi."
                    return
                }
                self.wifiDetectedSSID = ssid
                self.wifiHomeSSID = ssid
                self.wifiSetupError = nil
            }
        }
    }

    func startWiFiSetup(code: String, homeSSID: String, homePassword: String) {
        let normalizedCode = code.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedSSID = homeSSID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard normalizedCode.range(of: "^[0-9]{6}$", options: .regularExpression) != nil else {
            wifiSetupError = "Enter the six-digit WIFI PIN shown on the ticker."
            return
        }
        guard !normalizedSSID.isEmpty, normalizedSSID.utf8.count <= 32, homePassword.utf8.count <= 64 else {
            wifiSetupError = "Enter a Wi-Fi name of up to 32 bytes and a password of up to 64 bytes. Open networks need no password."
            return
        }

        wifiSetupError = nil
        wifiSetupStatus = "Searching for the ticker over Bluetooth..."
        isWifiSetupInProgress = true
        bleProvisioning.start(code: normalizedCode, ssid: normalizedSSID, password: homePassword) { pairingCode in
            Task { @MainActor in
                if let pairingCode {
                    self.wifiSetupStatus = "Wi-Fi saved. Pairing this app with the ticker..."
                    self.pairTicker(
                        code: pairingCode,
                        name: self.pairName.isEmpty ? "My Ticker" : self.pairName,
                        shareGroup: self.canShareTickerGroup,
                        onSuccess: {
                            self.isWifiSetupInProgress = false
                            self.wifiSetupStatus = "Wi-Fi saved. Ticker paired successfully."
                        },
                        onFailure: { message in
                            self.isWifiSetupInProgress = false
                            self.wifiSetupStatus = ""
                            self.wifiSetupError = "Wi-Fi saved, but app pairing failed: \(message)"
                        }
                    )
                } else {
                    self.isWifiSetupInProgress = false
                    self.wifiSetupStatus = "Wi-Fi saved. Wait for APP PAIR, then enter that code in Add ticker."
                }
            }
        } onFailure: { message in
            Task { @MainActor in
                self.isWifiSetupInProgress = false
                self.wifiSetupStatus = ""
                self.wifiSetupError = message
            }
        }
    }

    // === 1. FETCH DATA (Read) ===
    func fetchData() {
        let base = getBaseURL()
        if base.isEmpty { self.connectionStatus = "Invalid URL"; self.statusColor = .red; return }
        guard let tickerID = savedTickerID,
              controllerToken(for: tickerID) != nil,
              let url = tickerURL(tickerID, suffix: "/data"),
              let request = authorizedRequest(url: url, method: "GET", tickerID: tickerID) else {
            self.isServerReachable = true
            self.updateOverallStatus()
            return
        }

        URLSession.shared.dataTask(with: request) { data, _, error in
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
                    let scheduleSource = decoded.meta.schedule?.source ?? "base"
                    self.scheduleActive = scheduleSource == "time" || scheduleSource == "condition"

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
                        if let sharedTeams = self.sharedMyTeams {
                            self.state.my_teams = sharedTeams
                        } else {
                            self.sharedMyTeams = decoded.settings.my_teams
                        }
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
        sharedMyTeams = state.my_teams

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
    func saveSettings(scheduleOverride: Bool = false) {
        self.isEditing = true   // LOCK: block polling while save is in-flight
        guard let validID = self.savedTickerID,
              let url = tickerURL(validID),
              var request = authorizedRequest(url: url, method: "PATCH", tickerID: validID) else {
            self.isEditing = false
            return
        }

        do {
            var payload: [String: Any] = ["display_settings": v2DisplaySettingsPayload()]
            if scheduleOverride {
                payload["schedule_override"] = true
            }
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
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
                            self.selectActiveTicker(nil)
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
                    self.syncSharedMyTeams(excluding: validID)
                }
            }
            currentSaveTask?.resume()
        } catch { print("Save Error") }
    }

    private func syncSharedMyTeams(excluding activeID: String) {
        guard let teams = sharedMyTeams else { return }
        for device in devices where device.id != activeID {
            guard let url = tickerURL(device.id),
                  var request = authorizedRequest(url: url, method: "PATCH", tickerID: device.id) else { continue }
            request.httpBody = try? JSONSerialization.data(
                withJSONObject: ["display_settings": ["my_teams": teams]]
            )
            URLSession.shared.dataTask(with: request).resume()
        }
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
        let activeSettings = activeTicker?.settings
        return [
            "active_sports": state.active_sports,
            "my_teams": sharedMyTeams ?? state.my_teams,
            "mode": state.mode,
            "sports_filter": state.sports_filter,
            "sports_presentation": pinned.isEmpty ? "rotation" : "pinned",
            "pinned_content_id": pinned,
            "brightness": brightness ?? activeSettings?.brightness ?? 100,
            "inverted": inverted ?? activeSettings?.inverted ?? false,
            "timezone": TimeZone.current.identifier,
            "weather_city": state.weather_city,
            "weather_lat": state.weather_lat,
            "weather_lon": state.weather_lon,
            "airport_code_iata": state.airport_code_iata,
            "airport_code_icao": state.airport_code_icao,
            "airport_name": state.airport_name,
            "track_flight_id": state.track_flight_id,
            "track_guest_name": state.track_guest_name,
            "live_delay_mode": liveDelayMode ?? activeSettings?.live_delay_mode ?? false,
            "live_delay_seconds": liveDelaySeconds ?? activeSettings?.live_delay_seconds ?? 45,
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
        deviceListTask?.cancel()
        let tickerID = savedTickerID
        let token = tickerID.flatMap(controllerToken)
        guard let tickerID,
              let token,
              let url = URL(string: "\(getBaseURL())/api/v2/tickers"),
              let request = authorizedRequest(url: url, method: "GET", tickerID: tickerID) else {
            deviceListGate.invalidate()
            deviceListTask = nil
            self.devices.removeAll()
            self.updateOverallStatus()
            return
        }

        let requestIdentity = deviceListGate.begin(tickerID: tickerID, authorizationToken: token)
        let task = URLSession.shared.dataTask(with: request) { data, _, _ in
            guard let data, let decoded = try? JSONDecoder().decode(V2TickerList.self, from: data) else { return }
            DispatchQueue.main.async {
                guard self.deviceListGate.accepts(
                    requestIdentity,
                    activeTickerID: self.savedTickerID,
                    activeAuthorizationToken: self.savedTickerID.flatMap(self.controllerToken)
                ) else { return }

                // The backend list is authoritative for membership. Every returned row is
                // authorized by the request token and remains visible after a token replacement.
                self.isServerReachable = true
                self.devices = decoded.tickers.map(\.tickerDevice)
                if decoded.tickers.isEmpty {
                    self.games = []
                }
                if self.isSportsOnly && self.state.mode != "sports" {
                    self.state.mode = "sports"
                    self.saveSettings()
                }
                self.updateOverallStatus()
            }
        }
        deviceListTask = task
        task.resume()
    }

    // Device refresh owns the list only. Selection changes happen in pairing, unpairing,
    // or an explicit user action, so an empty or delayed response cannot relatch another ID.
    func updateOverallStatus() {
        if !isServerReachable { self.connectionStatus = "Server Offline"; self.statusColor = .red; return }
        // If we have devices OR a latched ID, we are effectively connected
        if devices.isEmpty && savedTickerID == nil { self.connectionStatus = "Server Online (No Ticker)"; self.statusColor = .orange; return }
        if scheduleActive {
            self.connectionStatus = "Connected • Schedule"
            self.statusColor = .yellow
            return
        }
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

    private func pairingServerMessage(_ data: Data?) -> String? {
        guard let data,
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let error = root["error"] as? [String: Any],
              let message = error["message"] as? String else { return nil }
        return message
    }

    func pairTicker(
        code: String,
        name: String,
        shareGroup: Bool = true,
        onSuccess: (() -> Void)? = nil,
        onFailure: ((String) -> Void)? = nil
    ) {
            let base = getBaseURL()
            guard let url = URL(string: "\(base)/api/v2/pairings/exchange") else {
                self.pairError = "Invalid Server URL"
                onFailure?("Invalid server URL")
                return
            }

            var body: [String: Any] = ["pairing_code": code]
            if shareGroup,
               let groupID = controllerGroupID,
               let groupSecret = controllerGroupSecret() {
                body["controller_group_id"] = groupID
                body["controller_group_secret"] = groupSecret
            }

            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")

            do {
                req.httpBody = try JSONSerialization.data(withJSONObject: body)
            } catch {
                self.pairError = "Failed to encode pairing data"
                onFailure?("Failed to encode pairing data")
                return
            }
            req.timeoutInterval = 15

            URLSession.shared.dataTask(with: req) { data, response, error in
                if let error = error {
                    let message = "Network error: \(error.localizedDescription)"
                    DispatchQueue.main.async {
                        self.pairError = message
                        onFailure?(message)
                    }
                    return
                }

                // Check HTTP Status Code
                if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode != 201 {
                     let detail = self.pairingServerMessage(data).map { ": \($0)" } ?? ""
                     let message = "Server error (HTTP \(httpResponse.statusCode))\(detail)"
                     DispatchQueue.main.async {
                         self.pairError = message
                         onFailure?(message)
                     }
                     return
                }

                guard let d = data else {
                    DispatchQueue.main.async {
                        self.pairError = "No data received from server"
                        onFailure?("No data received from server")
                    }
                    return
                }

                // Decode Response
                if let res = try? JSONDecoder().decode(PairingExchangeResponse.self, from: d), let newID = res.ticker_id {
                    DispatchQueue.main.async {
                        if let groupID = res.controller_group_id {
                            if let groupSecret = res.controller_group_secret {
                                guard self.saveControllerGroup(id: groupID, secret: groupSecret) else {
                                    self.showPairSuccess = false
                                    self.pairError = "Pairing failed: the shared app group could not be saved securely."
                                    onFailure?("The shared app group could not be saved securely")
                                    return
                                }
                            } else {
                                self.controllerGroupID = groupID
                            }
                        }
                        guard self.selection.selectPairedTicker(
                            newID,
                            tokenWasSaved: self.saveControllerToken(res.controller_token, for: newID)
                        ) else {
                            self.showPairSuccess = false
                            self.pairError = "Pairing failed: the controller token could not be saved securely."
                            onFailure?("The controller token could not be saved securely")
                            return
                        }
                        self.savedTickerID = self.selection.activeTickerID
                        self.showPairSuccess = true
                        self.updateTickerName(name, tickerID: newID)
                        // Start one latest-generation list request after selection and token storage.
                        self.fetchDevices()
                        self.fetchData()
                        self.fetchSpotifyStatus()
                        onSuccess?()
                    }
                } else {
                    DispatchQueue.main.async {
                        self.pairError = "Failed to process server response"
                        onFailure?("Failed to process server response")
                    }
                }
            }.resume()
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
                    self.connectionStatus = "Unpair failed\(status.map { " (HTTP \($0))" } ?? "")"
                    self.statusColor = .red
                }
                return
            }
            DispatchQueue.main.async {
                self.devices.removeAll { $0.id == id }
                self.games.removeAll()
                self.removeControllerToken(for: id)
                if self.savedTickerID == id {
                    self.deviceListTask?.cancel()
                    self.deviceListGate.invalidate()
                    var nextSelection = DeviceSelectionReducer(activeTickerID: self.savedTickerID)
                    let remainingAuthorizedIDs = self.devices
                        .filter { self.controllerToken(for: $0.id) != nil }
                        .map(\.id)
                    nextSelection.selectAfterRemoving(id, remainingTickerIDs: remainingAuthorizedIDs)
                    self.selectActiveTicker(nextSelection.activeTickerID)
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
        guard let url = tickerURL(id),
              var req = authorizedRequest(url: url, method: "PATCH", tickerID: id) else {
            print("❌ Invalid URL for device update")
            return
        }
        let body: [String: Any] = ["display_settings": v2DeviceSettingsPatch(
            brightness: brightness,
            scrollSpeed: speed,
            seamless: seamless,
            inverted: inverted,
            liveDelayMode: liveDelayMode,
            liveDelaySeconds: delaySeconds
        )]

        print("📤 Sending Update to \(id): \(body)")

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

    private func v2DeviceSettingsPatch(
        brightness: Double? = nil,
        scrollSpeed: Double? = nil,
        seamless: Bool? = nil,
        inverted: Bool? = nil,
        liveDelayMode: Bool? = nil,
        liveDelaySeconds: Int? = nil
    ) -> [String: Any] {
        var patch: [String: Any] = [:]
        if let brightness { patch["brightness"] = brightness * 100 }
        if let scrollSpeed { patch["scroll_speed"] = scrollSpeed }
        if let seamless { patch["scroll_seamless"] = seamless }
        if let inverted { patch["inverted"] = inverted }
        if let liveDelayMode { patch["live_delay_mode"] = liveDelayMode }
        if let liveDelaySeconds { patch["live_delay_seconds"] = liveDelaySeconds }
        return patch
    }

    private func updateTickerName(_ name: String, tickerID: String) {
        guard let url = tickerURL(tickerID),
              var request = authorizedRequest(url: url, method: "PATCH", tickerID: tickerID) else { return }
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
                    self.pairCodeAlertMessage = "\(pairing.pairing_code)\nExpires in 10 minutes."
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
