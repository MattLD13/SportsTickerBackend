import Foundation
import Observation

/// The connection line of the Home screen.
struct ConnectionStatus: Equatable {
    enum Tone { case neutral, good, warning, failure, schedule }
    var text: String
    var tone: Tone
}

struct WiFiSetup {
    var code = ""
    var ssid = ""
    var password = ""
    var detectedSSID = ""
    var usesCurrentNetwork = true
    var status = ""
    var error: String?
    var inProgress = false
}

struct SpotifyState {
    var status = "Checking Spotify..."
    var accountName: String?
    var accounts: [SpotifyAccount] = []
    var error: String?
    var connecting = false
}

/// The state and the actions of the app. Every screen reads this store, and every user action is a method here.
/// A network result applies only when the server, the active ticker, and its token are the ones that the request used.
@Observable
final class TickerStore {
    // Display state of the active ticker
    var settings = DisplaySettings()
    var feed: [FeedItem] = []
    var schedule: ScheduleStatus?
    var connection = ConnectionStatus(text: "Connecting...", tone: .neutral)
    /// True while a user edit is in progress. Polling stops, so a read cannot undo the edit.
    var isEditing = false
    var operationError: String?
    var weatherInput = "New York"

    // Tickers and catalog
    var devices: [TickerRecord] = []
    var leagues: [League] = []
    var teams: [String: [Team]] = [:]
    var modeSymbols: [String: String] = [:]

    // Pairing, setup, and Spotify
    var pairCode = ""
    var pairName = ""
    var pairError: String?
    var pairSucceeded = false
    var pairCodeMessage: String?
    var wifi = WiFiSetup()
    var spotify = SpotifyState()

    var serverURL: String {
        didSet {
            guard serverURL != oldValue else { return }
            session.serverURL = serverURL
            api.setBaseURL(serverURL)
            invalidate()
        }
    }

    @ObservationIgnored let session: Session
    @ObservationIgnored let api: APIClient
    @ObservationIgnored let platform: any TickerPlatform
    @ObservationIgnored private var polling = PollingPolicy()
    @ObservationIgnored private var lastDeviceRefresh: Date = .distantPast
    @ObservationIgnored private var loop: Task<Void, Never>?
    /// The generation of the display read in progress, or nil.
    @ObservationIgnored private var activeRead: Int?
    @ObservationIgnored private var teamSave: Task<Void, Never>?
    @ObservationIgnored private var epoch = 0
    @ObservationIgnored private var readGeneration = 0
    @ObservationIgnored var reachable = false
    @ObservationIgnored private var saving = false
    @ObservationIgnored private var savePending = false
    @ObservationIgnored private var pendingOverride = false
    /// The ticker whose settings `settings` holds. It is nil until the first read.
    @ObservationIgnored private(set) var settingsTickerID: String?

    init(session: Session, transport: any HTTPTransport = URLSessionTransport(), platform: any TickerPlatform) {
        self.session = session
        self.platform = platform
        serverURL = session.serverURL
        api = APIClient(baseURL: session.serverURL, transport: transport)
        activeTickerID = session.activeTickerID
    }

    // Active ticker

    private(set) var activeTickerID: String? {
        didSet { session.activeTickerID = activeTickerID }
    }

    var activeTicker: TickerRecord? { devices.first { $0.id == activeTickerID } }
    var needsSetup: Bool { activeTickerID == nil }
    var isSportsOnly: Bool { activeTicker?.isSportsOnly ?? false }
    var isSportsMode: Bool { !["stock", "weather", "clock", "music", "flights", "airports"].contains(settings.mode) }
    var canShareGroup: Bool { session.canShareGroup }
    var myTeams: [String] { settings.myTeams }

    /// The name, the family, and the position of the active ticker, such as "Kitchen • MINI • 1/2".
    var activeTickerLabel: String {
        guard let ticker = activeTicker else { return "Choose a ticker" }
        let family = ticker.profile?.productFamily.uppercased() ?? "TICKER"
        let index = devices.firstIndex { $0.id == ticker.id }.map { "\($0 + 1)/\(max(1, devices.count))" } ?? ""
        return [ticker.name, family, index].filter { !$0.isEmpty }.joined(separator: " • ")
    }

    func modeSymbol(_ mode: String) -> String { modeSymbols[mode] ?? SchedulePresentation.modeSymbol(mode) }

    func isPinned(_ item: FeedItem) -> Bool { settings.isPinned && settings.pinnedContentID.lowercased() == item.pinID }

    func switchTicker(_ id: String) {
        guard devices.contains(where: { $0.id == id }), id != activeTickerID else { return }
        select(id)
        feed = []
        leagues = []
        modeSymbols = [:]
        reachable = false
        Task {
            await refreshData()
            await loadCatalog()
            await refreshSpotify()
        }
    }

    func select(_ id: String?) {
        invalidate()
        activeTickerID = id
    }

    /// Drop every request of the replaced server, ticker, or token.
    private func invalidate() {
        epoch += 1
        readGeneration += 1
        schedule = nil
        teamSave?.cancel()
        saving = false
        savePending = false
        pendingOverride = false
        spotify.connecting = false
        isEditing = false
        settingsTickerID = nil
    }

    // Requests

    struct Scope: Equatable {
        let server: String
        let tickerID: String
        let token: String
        let epoch: Int
    }

    func scope(_ tickerID: String? = nil) -> Scope? {
        guard let id = tickerID ?? activeTickerID,
              let token = session.authorization(for: id, among: devices.map(\.id)) else { return nil }
        return Scope(server: api.baseURL, tickerID: id, token: token, epoch: epoch)
    }

    func isCurrent(_ scope: Scope) -> Bool { scope == self.scope(scope.tickerID) && scope.tickerID == activeTickerID }

    // Polling

    /// Start the polling loop: display data at the interval of the mode, and the ticker list every five seconds.
    func start() {
        loop?.cancel()
        Task {
            await refreshData()
            await loadCatalog()
            await refreshDevices()
            await refreshSpotify()
        }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                self?.tick(at: Date())
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        }
    }

    func stop() {
        loop?.cancel()
        loop = nil
    }

    func tick(at now: Date) {
        if polling.shouldPoll(at: now, mode: settings.mode, isEditing: isEditing) {
            Task {
                await refreshData()
                if leagues.isEmpty { await loadCatalog() }
            }
        }
        if !isEditing, now.timeIntervalSince(lastDeviceRefresh) >= 5 {
            lastDeviceRefresh = now
            Task { await refreshDevices() }
        }
    }

    /// Poll fast for 30 seconds, so a change shows on the feed quickly.
    func beginBurst() { polling.beginBurst(at: Date()) }

    // Display data

    /// Read the display data. A save or a ticker change starts a new generation, so an older read is ignored.
    func refreshData() async {
        guard activeRead != readGeneration else { return }
        guard let scope = scope() else {
            connection = ConnectionStatus(text: activeTickerID == nil ? "Pair a ticker to connect" : "Pair this ticker again to reconnect",
                                          tone: .warning)
            return
        }
        let generation = readGeneration
        activeRead = generation
        let result: Result<DisplayData, Error>
        do { result = .success(try await api.send(API.data(scope.tickerID), token: scope.token)) } catch { result = .failure(error) }
        if activeRead == generation { activeRead = nil }
        guard generation == readGeneration, isCurrent(scope) else { return }
        switch result {
        case .success(let data): apply(data, tickerID: scope.tickerID)
        case .failure(let error):
            reachable = false
            connection = ConnectionStatus(text: error.localizedDescription, tone: .failure)
        }
    }

    private func apply(_ data: DisplayData, tickerID: String) {
        reachable = true
        schedule = data.meta.schedule
        if !isEditing {
            settings = data.settings
            settingsTickerID = tickerID
            if data.settings.isPinned { settings.pinnedContentID = data.settings.pinnedContentID.lowercased() }
            if let shared = session.sharedTeams { settings.myTeams = shared } else { session.sharedTeams = data.settings.myTeams }
            if !data.settings.weatherCity.isEmpty { weatherInput = data.settings.weatherCity }
        }
        feed = FeedOrder.items(data, pinnedID: settings.isPinned ? settings.pinnedContentID : nil)
        updateStatus()
    }

    func updateStatus() {
        if !reachable { connection = ConnectionStatus(text: "Server Offline", tone: .failure); return }
        if devices.isEmpty && activeTickerID == nil {
            connection = ConnectionStatus(text: "Server Online (No Ticker)", tone: .warning)
        } else if schedule?.active == true {
            connection = ConnectionStatus(text: "Connected • Schedule", tone: .schedule)
        } else {
            connection = ConnectionStatus(text: "Connected • \(feed.count) Items", tone: .good)
        }
    }

    // Saving display settings

    /// Send the display settings. One save runs at a time. Edits during a save go in one follow-up save.
    func save(scheduleOverride: Bool = false) {
        isEditing = true
        guard let scope = scope() else {
            isEditing = false
            operationError = "Pair this ticker before changing its settings."
            return
        }
        if saving {
            savePending = true
            pendingOverride = pendingOverride || scheduleOverride
            return
        }
        saving = true
        readGeneration += 1
        var values = settings
        values.myTeams = session.sharedTeams ?? settings.myTeams
        let change = TickerChange(displaySettings: .display(values, timezone: TimeZone.current.identifier),
                                  scheduleOverride: scheduleOverride ? true : nil)
        Task {
            var failure: Error?
            do { _ = try await api.send(API.updateTicker(scope.tickerID, change), token: scope.token) } catch { failure = error }
            guard isCurrent(scope) else { return }
            saving = false
            if savePending {
                let override = pendingOverride
                savePending = false
                pendingOverride = false
                save(scheduleOverride: override)
                return
            }
            isEditing = false
            if let failure {
                operationError = failure.localizedDescription
                return
            }
            operationError = nil
            shareTeams(excluding: scope.tickerID)
            await refreshData()
        }
    }

    /// Save My Teams 1.5 seconds after the last change, so quick taps send one request.
    func scheduleTeamSave() {
        teamSave?.cancel()
        teamSave = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            guard !Task.isCancelled else { return }
            self?.save()
        }
    }

    /// Copy My Teams to the other paired tickers.
    private func shareTeams(excluding tickerID: String) {
        guard let teams = session.sharedTeams else { return }
        for device in devices where device.id != tickerID {
            guard let scope = scope(device.id) else { continue }
            let change = TickerChange(displaySettings: DisplaySettingsPatch(myTeams: teams))
            Task { _ = try? await api.send(API.updateTicker(scope.tickerID, change), token: scope.token) }
        }
    }
}
