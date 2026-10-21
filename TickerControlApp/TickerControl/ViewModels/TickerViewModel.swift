import SwiftUI
import Foundation
import Combine
import UIKit
import CoreLocation
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
    @Published var operationError: String?
    @Published var showPairSuccess: Bool = false
    @Published var serverURL: String {
        didSet {
            UserDefaults.standard.set(serverURL, forKey: "serverURL")
            if oldValue != serverURL { invalidateRequests() }
        }
    }
    @Published var weatherLocInput: String = "New York"
    @Published var connectionStatus: String = "Connecting..."
    @Published var statusColor: Color = .gray
    @Published var scheduleStatus: TickerScheduleStatus?
    var scheduleActive: Bool { scheduleStatus?.active ?? false }
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
    private let polling = TickerPollingCoordinator()
    private let httpClient: any TickerHTTPTransport
    private let credentialStore: any TickerCredentialStore
    private var currentSaveTask: (any TickerHTTPTask)?
    private var savePending = false
    private var pendingScheduleOverride = false
    private var deviceListTask: (any TickerHTTPTask)?
    private var deviceListGate = TickerRequestGate()
    private var displayTask: (any TickerHTTPTask)?
    private var displayGate = TickerRequestGate()
    private var saveGate = TickerRequestGate()
    private var weatherGate = TickerRequestGate()
    private var spotifyGate = TickerRequestGate()
    private var overrideGate = TickerRequestGate()
    private var selection: DeviceSelectionReducer
    private var spotifyAuthorizationSession: ASWebAuthenticationSession?
    private var wifiLocationManager: CLLocationManager?
    private let bleProvisioning = BLEProvisioningCoordinator()
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
        invalidateRequests()
        selection.select(tickerID)
        savedTickerID = tickerID
    }

    private func invalidateRequests() {
        scheduleStatus = nil
        displayGate.invalidate()
        saveGate.invalidate()
        deviceListGate.invalidate()
        weatherGate.invalidate()
        spotifyGate.invalidate()
        overrideGate.invalidate()
        displayTask?.cancel()
        currentSaveTask?.cancel()
        deviceListTask?.cancel()
        displayTask = nil
        currentSaveTask = nil
        savePending = false
        pendingScheduleOverride = false
        deviceListTask = nil
        polling.cancelPendingSave()
        spotifyAuthorizationSession?.cancel()
        spotifyAuthorizationSession = nil
        isConnectingSpotify = false
        isEditing = false
    }

    private func authorizationToken(for tickerID: String) -> String? {
        if let token = controllerToken(for: tickerID) { return token }
        guard controllerGroupID != nil else { return nil }
        return devices.lazy.compactMap { self.controllerToken(for: $0.id) }.first
    }

    func switchToTicker(_ tickerID: String) {
        guard devices.contains(where: { $0.id == tickerID }), tickerID != savedTickerID else { return }
        selectActiveTicker(tickerID)
        games.removeAll()
        leagueOptions.removeAll()
        modeSymbols.removeAll()
        isServerReachable = false
        fetchData()
        fetchLeagueOptions()
        fetchModeOptions()
        fetchSpotifyStatus()
    }

    private func controllerToken(for tickerID: String) -> String? {
        credentialStore.read(service: "matt.TickerControl.controller-token", account: tickerID)
    }

    private func controllerGroupSecret() -> String? {
        credentialStore.read(service: "matt.TickerControl.controller-group-secret", account: getBaseURL())
    }

    @discardableResult
    private func saveControllerGroup(id: String, secret: String) -> Bool {
        guard credentialStore.write(secret, service: "matt.TickerControl.controller-group-secret", account: getBaseURL()) else {
            return false
        }
        controllerGroupID = id
        return true
    }

    @discardableResult
    private func saveControllerToken(_ token: String, for tickerID: String) -> Bool {
        credentialStore.write(token, service: "matt.TickerControl.controller-token", account: tickerID)
    }

    private func removeControllerToken(for tickerID: String) {
        credentialStore.remove(service: "matt.TickerControl.controller-token", account: tickerID)
    }

    private func tickerURL(_ tickerID: String, suffix: String = "") -> URL? {
        let identifier = tickerID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? tickerID
        return URL(string: "\(getBaseURL())/api/v2/tickers/\(identifier)\(suffix)")
    }

    private func authorizedRequest(url: URL, method: String, tickerID: String? = nil) -> URLRequest? {
        let identifier = tickerID ?? savedTickerID
        guard let identifier else { return nil }
        // A group session can authorize every ticker in the same app group.
        let token = authorizationToken(for: identifier)
        guard let token else { return nil }
        return TickerHTTPClient.authorizedRequest(url: url, method: method, token: token)
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
                request.httpBody = try TickerHTTPClient.jsonData( body)
            } catch {
                completion(.failure(error))
                return
            }
        }
        httpClient.dataTask(with: request) { data, response, error in
            let result: Result<T, Error>
            if let error {
                result = .failure(error)
            } else if let httpResponse = response as? HTTPURLResponse,
                      !(200...299).contains(httpResponse.statusCode) {
                result = .failure(TickerScheduleRequestError.server(TickerHTTPClient.serverMessage(data) ?? "Schedule request failed (HTTP \(httpResponse.statusCode))."))
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

    func setCurrentScheduleOverride(_ enabled: Bool, completion: @escaping (Result<Void, Error>) -> Void) {
        guard let tickerID = savedTickerID, let token = authorizationToken(for: tickerID) else {
            completion(.failure(TickerScheduleRequestError.authorization))
            return
        }
        let server = getBaseURL()
        let identity = overrideGate.begin(tickerID: tickerID, authorizationToken: token, serverURL: server)
        let isCurrent = {
            self.overrideGate.accepts(identity, activeTickerID: self.savedTickerID,
                activeAuthorizationToken: self.savedTickerID.flatMap(self.authorizationToken), activeServerURL: self.getBaseURL())
        }
        setScheduleOverride(tickerID: tickerID, enabled: enabled) { result in
            guard isCurrent() else { completion(.failure(CancellationError())); return }
            switch result {
            case .failure(let error): completion(.failure(error))
            case .success:
                self.displayTask?.cancel()
                self.displayTask = nil
                self.displayGate.invalidate()
                self.startBurstPolling()
                self.fetchData()
                self.fetchSchedule(for: tickerID) { result in
                    guard isCurrent() else { completion(.failure(CancellationError())); return }
                    switch result {
                    case .success(let value): self.scheduleStatus = value.effective; completion(.success(()))
                    case .failure(let error): completion(.failure(error))
                    }
                }
            }
        }
    }

    override convenience init() {
        self.init(httpClient: TickerHTTPClient())
    }

    init(httpClient: any TickerHTTPTransport, credentialStore: any TickerCredentialStore = KeychainTickerCredentialStore()) {
        self.httpClient = httpClient
        self.credentialStore = credentialStore
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

        polling.start(
            state: { [weak self] in (self?.state.mode ?? "sports", self?.isEditing ?? true) },
            poll: { [weak self] in
                self?.fetchData()
                if self?.leagueOptions.isEmpty == true { self?.fetchLeagueOptions() }
            },
            refreshDevices: { [weak self] in self?.fetchDevices() }
        )
    }
    /// Call this whenever the user switches modes. The timer will poll every 1 s
    /// for the next 30 s, giving the app (and the hardware board) fast feedback.
    func startBurstPolling() {
        polling.beginBurst()
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

    func cancelWiFiSetup() {
        bleProvisioning.cancel()
        isWifiSetupInProgress = false
        wifiHomePassword = ""
    }

    // Display reads belong to one server, ticker, and request generation.
    func fetchData() {
        guard displayTask == nil else { return }
        guard let tickerID = savedTickerID,
              let token = authorizationToken(for: tickerID),
              let url = tickerURL(tickerID, suffix: "/data"),
              let request = authorizedRequest(url: url, method: "GET", tickerID: tickerID) else {
            connectionStatus = savedTickerID == nil ? "Pair a ticker to connect" : "Pair this ticker again to reconnect"
            statusColor = .orange
            return
        }
        let identity = displayGate.begin(tickerID: tickerID, authorizationToken: token, serverURL: getBaseURL())
        displayTask = httpClient.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                guard self.displayGate.accepts(identity, activeTickerID: self.savedTickerID,
                    activeAuthorizationToken: self.savedTickerID.flatMap(self.authorizationToken),
                    activeServerURL: self.getBaseURL()) else { return }
                self.displayTask = nil
                if let message = TickerHTTPClient.failureMessage(data: data, response: response, error: error) {
                    self.isServerReachable = false
                    self.connectionStatus = message
                    self.statusColor = .red
                    return
                }
                guard let data else {
                    self.connectionStatus = "The server returned an empty display response."
                    self.statusColor = .red
                    return
                }
                do {
                    let display = try TickerDisplayResponse(data: data)
                    let decoded = display.response
                    self.isServerReachable = true
                    self.scheduleStatus = decoded.meta.schedule
                    if !self.isEditing {
                        let pins = decoded.settings.pinned_content_id.isEmpty ? [] : [self.normalizedPin(decoded.settings.pinned_content_id)]
                        self.pinnedGameIDs = pins
                        self.state = decoded.settings
                        self.state.ticker_id = tickerID
                        if let shared = self.sharedMyTeams {
                            self.state.my_teams = shared
                        } else {
                            self.sharedMyTeams = decoded.settings.my_teams
                        }
                        self.state.pinned_games = pins
                        self.state.pinned_game = pins.first
                        if !decoded.settings.weather_city.isEmpty {
                            self.weatherLocInput = decoded.settings.weather_city
                        }
                    }
                    self.games = display.orderedGames(pinnedIDs: self.pinnedGameIDs)
                    self.updateOverallStatus()
                } catch {
                    self.connectionStatus = "The server returned invalid ticker data."
                    self.statusColor = .red
                }
            }
        }
        displayTask?.resume()
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
        polling.debounceSave { [weak self] in self?.saveSettings() }
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
    // Serialize writes and combine pending edits before sending the next state.
    func saveSettings(scheduleOverride: Bool = false) {
        isEditing = true
        guard let tickerID = savedTickerID,
              let token = authorizationToken(for: tickerID),
              let url = tickerURL(tickerID),
              var request = authorizedRequest(url: url, method: "PATCH", tickerID: tickerID) else {
            isEditing = false
            operationError = "Pair this ticker before changing its settings."
            return
        }
        if currentSaveTask != nil {
            savePending = true
            pendingScheduleOverride = pendingScheduleOverride || scheduleOverride
            return
        }
        do {
            var payload: [String: Any] = ["display_settings": v2DisplaySettingsPayload()]
            if scheduleOverride { payload["schedule_override"] = true }
            request.httpBody = try TickerHTTPClient.jsonData( payload)
            request.timeoutInterval = 15
            let identity = saveGate.begin(tickerID: tickerID, authorizationToken: token, serverURL: getBaseURL())
            displayGate.invalidate()
            displayTask?.cancel()
            displayTask = nil
            currentSaveTask = httpClient.dataTask(with: request) { data, response, error in
                DispatchQueue.main.async {
                    guard self.saveGate.accepts(identity, activeTickerID: self.savedTickerID,
                        activeAuthorizationToken: self.savedTickerID.flatMap(self.authorizationToken),
                        activeServerURL: self.getBaseURL()) else { return }
                    self.currentSaveTask = nil
                    if self.savePending {
                        let override = self.pendingScheduleOverride
                        self.savePending = false
                        self.pendingScheduleOverride = false
                        self.saveSettings(scheduleOverride: override)
                        return
                    }
                    self.isEditing = false
                    if let message = TickerHTTPClient.failureMessage(data: data, response: response, error: error) {
                        self.operationError = message
                        return
                    }
                    self.operationError = nil
                    self.fetchData()
                    self.syncSharedMyTeams(excluding: tickerID)
                }
            }
            currentSaveTask?.resume()
        } catch {
            isEditing = false
            operationError = "These settings could not be encoded. Check the entered values."
        }
    }

    private func syncSharedMyTeams(excluding activeID: String) {
        guard let teams = sharedMyTeams else { return }
        for device in devices where device.id != activeID {
            guard let url = tickerURL(device.id),
                  var request = authorizedRequest(url: url, method: "PATCH", tickerID: device.id) else { continue }
            request.httpBody = try? JSONSerialization.data(
                withJSONObject: ["display_settings": ["my_teams": teams]]
            )
            httpClient.dataTask(with: request).resume()
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
            "custom_stock_symbols": state.custom_stock_symbols,
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
        ]
    }

    // --- STANDARD HELPERS ---

    func searchStockSymbols(_ query: String) async throws -> [StockSymbolOption] {
        guard var components = URLComponents(string: getBaseURL() + "/api/v2/catalog/stocks") else {
            throw URLError(.badURL)
        }
        components.queryItems = [URLQueryItem(name: "q", value: query)]
        guard let url = components.url else { throw URLError(.badURL) }
        return try await withCheckedThrowingContinuation { continuation in
            var request = URLRequest(url: url)
            request.timeoutInterval = 8
            httpClient.dataTask(with: request) { data, response, error in
                if let message = TickerHTTPClient.failureMessage(data: data, response: response, error: error) {
                    continuation.resume(throwing: NSError(domain: "StockSearch", code: 1,
                        userInfo: [NSLocalizedDescriptionKey: message]))
                    return
                }
                do {
                    let result = try JSONDecoder().decode(StockSymbolSearchResponse.self, from: data ?? Data())
                    continuation.resume(returning: result.stocks)
                } catch { continuation.resume(throwing: error) }
            }.resume()
        }
    }

    func fetchLeagueOptions() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/v2/catalog/leagues") else { return }
        httpClient.dataTask(with: url) { data, _, _ in
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
        httpClient.dataTask(with: url) { data, _, _ in
            if let d = data, let decoded = try? JSONDecoder().decode(V2TeamCatalog.self, from: d) {
                DispatchQueue.main.async { self.allTeams[leagueID] = decoded.teams }
            }
        }.resume()
    }

    func fetchModeOptions() {
        let base = getBaseURL()
        guard let url = URL(string: "\(base)/api/v2/catalog/modes") else { return }
        httpClient.dataTask(with: url) { data, _, _ in
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
        let token = tickerID.flatMap(authorizationToken)
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

        let requestIdentity = deviceListGate.begin(tickerID: tickerID, authorizationToken: token, serverURL: getBaseURL())
        let task = httpClient.dataTask(with: request) { data, _, _ in
            guard let data, let decoded = try? JSONDecoder().decode(V2TickerList.self, from: data) else { return }
            DispatchQueue.main.async {
                guard self.deviceListGate.accepts(
                    requestIdentity,
                    activeTickerID: self.savedTickerID,
                    activeAuthorizationToken: self.savedTickerID.flatMap(self.authorizationToken),
                    activeServerURL: self.getBaseURL()
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
        guard let tickerID = savedTickerID, let token = authorizationToken(for: tickerID) else {
            operationError = "Pair a ticker before changing its weather location."
            return
        }
        let geocoder = CLGeocoder()
        let identity = weatherGate.begin(tickerID: tickerID, authorizationToken: token, serverURL: getBaseURL())
        isEditing = true
        geocoder.geocodeAddressString(weatherLocInput) { placemarks, error in
            DispatchQueue.main.async {
                guard self.weatherGate.accepts(identity, activeTickerID: self.savedTickerID,
                    activeAuthorizationToken: self.savedTickerID.flatMap(self.authorizationToken),
                    activeServerURL: self.getBaseURL()) else { return }
                guard error == nil, let place = placemarks?.first, let location = place.location,
                      let name = place.locality ?? place.name else {
                    self.isEditing = false
                    self.operationError = "That weather location could not be found. Check its city or ZIP code."
                    return
                }
                self.state.weather_city = name
                self.state.weather_lat = location.coordinate.latitude
                self.state.weather_lon = location.coordinate.longitude
                self.state.weather_location = self.weatherLocInput
                self.saveSettings()
            }
        }
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
                req.httpBody = try TickerHTTPClient.jsonData( body)
            } catch {
                self.pairError = "Failed to encode pairing data"
                onFailure?("Failed to encode pairing data")
                return
            }
            req.timeoutInterval = 15

            httpClient.dataTask(with: req) { data, response, error in
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
                     let detail = TickerHTTPClient.serverMessage(data).map { ": \($0)" } ?? ""
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
                        self.selectActiveTicker(self.selection.activeTickerID)
                        self.pairError = nil
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
        httpClient.dataTask(with: request) { data, response, error in
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
                self.removeControllerToken(for: id)
                if self.savedTickerID == id {
                    self.games.removeAll()
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
            operationError = "Pair this ticker before changing its settings."
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
            req.httpBody = try TickerHTTPClient.jsonData( body)
        } catch {
            operationError = "These device settings could not be encoded."
            return
        }

        httpClient.dataTask(with: req) { data, response, error in
            DispatchQueue.main.async {
                if let message = TickerHTTPClient.failureMessage(data: data, response: response, error: error) {
                    self.operationError = message
                    return
                }
                self.fetchDevices()
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
        request.httpBody = try? TickerHTTPClient.jsonData( ["name": name])
        httpClient.dataTask(with: request).resume()
    }

    func fetchSpotifyStatus() {
        guard let tickerID = savedTickerID,
              let token = authorizationToken(for: tickerID),
              let url = tickerURL(tickerID, suffix: "/integrations/spotify"),
              let request = authorizedRequest(url: url, method: "GET") else {
            spotifyStatus = "Connect a Ticker first"
            spotifyAccountName = nil
            spotifyAccounts = []
            return
        }
        let identity = spotifyGate.begin(tickerID: tickerID, authorizationToken: token, serverURL: getBaseURL())
        httpClient.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                guard self.spotifyGate.accepts(identity, activeTickerID: self.savedTickerID,
                    activeAuthorizationToken: self.savedTickerID.flatMap(self.authorizationToken),
                    activeServerURL: self.getBaseURL()) else { return }
                if let message = TickerHTTPClient.failureMessage(data: data, response: response, error: error) {
                    self.spotifyStatus = "Spotify unavailable"
                    self.spotifyError = message
                    return
                }
                guard let data, let status = try? JSONDecoder().decode(SpotifyStatus.self, from: data) else {
                    self.spotifyStatus = "Spotify unavailable"
                    self.spotifyError = "The server returned invalid Spotify data."
                    return
                }
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
        httpClient.dataTask(with: request) { data, response, error in
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
        httpClient.dataTask(with: request) { _, response, _ in
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
            withJSONObject: ["spotify_account_id": accountID.map { $0 as Any } ?? NSNull()]
        )
        httpClient.dataTask(with: request) { _, response, _ in
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
        httpClient.dataTask(with: request) { data, response, _ in
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
        httpClient.dataTask(with: request) { _, response, error in
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


}
// ==========================================
// MARK: - 3. UI COMPONENTS
// ==========================================
