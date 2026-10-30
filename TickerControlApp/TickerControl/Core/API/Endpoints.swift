import Foundation

/// One route of `docs/api.md`, with its method, path, body, and response type.
nonisolated struct Endpoint<Response> {
    var method: String
    var path: String
    var query: [(String, String)] = []
    var body: Data?
    var authorized = true
    var timeout: TimeInterval = 15
    var decode: (Data) throws -> Response
}

nonisolated extension Endpoint where Response: Decodable {
    init(_ method: String, _ path: String, query: [(String, String)] = [], body: Data? = nil, authorized: Bool = true,
         timeout: TimeInterval = 15) {
        self.init(method: method, path: path, query: query, body: body, authorized: authorized, timeout: timeout) {
            try JSONDecoder().decode(Response.self, from: $0)
        }
    }
}

/// The app routes of the ticker server.
nonisolated enum API {
    private static func json(_ value: some Encodable) -> Data? { try? JSONEncoder().encode(value) }
    private static func segment(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/"))) ?? value
    }
    private static func ticker(_ id: String, _ suffix: String = "") -> String { "/tickers/\(segment(id))\(suffix)" }

    // Pairing and tickers

    static func pair(_ request: PairRequest) -> Endpoint<PairResult> {
        Endpoint("POST", "/pair", body: json(request), authorized: false)
    }
    static func tickers() -> Endpoint<TickerList> { Endpoint("GET", "/tickers") }
    static func ticker(_ id: String) -> Endpoint<TickerRecord> { Endpoint("GET", ticker(id)) }
    static func updateTicker(_ id: String, _ change: TickerChange) -> Endpoint<TickerRecord> {
        Endpoint("PATCH", ticker(id), body: json(change))
    }
    static func deleteTicker(_ id: String) -> Endpoint<Empty> { Endpoint("DELETE", ticker(id)) }
    static func data(_ id: String) -> Endpoint<DisplayData> { Endpoint("GET", ticker(id, "/data")) }
    static func pairingCode(_ id: String) -> Endpoint<PairingCode> { Endpoint("POST", ticker(id, "/pairing-code")) }
    static func unpair(_ id: String) -> Endpoint<PairingCode> { Endpoint("DELETE", ticker(id, "/pairing")) }
    static func reboot(_ id: String) -> Endpoint<Empty> { Endpoint("POST", ticker(id, "/reboot")) }
    static func acknowledgeEvent(_ id: String, event: String) -> Endpoint<Empty> {
        Endpoint("POST", ticker(id, "/events/\(segment(event))/ack"))
    }

    // Schedule

    static func schedule(_ id: String) -> Endpoint<Schedule> { Endpoint("GET", ticker(id, "/schedule")) }
    static func createBlock(_ id: String, _ draft: ScheduleBlockDraft) -> Endpoint<ScheduleBlock> {
        Endpoint("POST", ticker(id, "/schedule/blocks"), body: json(draft))
    }
    static func updateBlock(_ id: String, block: String, _ draft: ScheduleBlockDraft) -> Endpoint<ScheduleBlock> {
        Endpoint("PATCH", ticker(id, "/schedule/blocks/\(segment(block))"), body: json(draft))
    }
    static func deleteBlock(_ id: String, block: String) -> Endpoint<Empty> {
        Endpoint("DELETE", ticker(id, "/schedule/blocks/\(segment(block))"))
    }
    static func createCondition(_ id: String, _ draft: ScheduleConditionDraft) -> Endpoint<ScheduleCondition> {
        Endpoint("POST", ticker(id, "/schedule/conditions"), body: json(draft))
    }
    static func updateCondition(_ id: String, condition: String, _ draft: ScheduleConditionDraft) -> Endpoint<ScheduleCondition> {
        Endpoint("PATCH", ticker(id, "/schedule/conditions/\(segment(condition))"), body: json(draft))
    }
    static func deleteCondition(_ id: String, condition: String) -> Endpoint<Empty> {
        Endpoint("DELETE", ticker(id, "/schedule/conditions/\(segment(condition))"))
    }

    // Spotify

    static func spotify(_ id: String) -> Endpoint<SpotifyStatus> { Endpoint("GET", ticker(id, "/spotify")) }
    static func unlinkSpotify(_ id: String, account: String? = nil) -> Endpoint<Empty> {
        Endpoint("DELETE", ticker(id, account.map { "/spotify/\(segment($0))" } ?? "/spotify"))
    }
    static func spotifyLogin(_ id: String) -> Endpoint<SpotifyLogin> { Endpoint("POST", ticker(id, "/spotify/login")) }
    static func spotifyPriority(_ id: String, account: String?) -> Endpoint<Empty> {
        Endpoint("PATCH", ticker(id, "/spotify/priority"), body: json(SpotifyPriority(spotifyAccountID: account)))
    }

    // Catalog

    static func modes() -> Endpoint<ModeCatalog> { Endpoint("GET", "/modes", authorized: false) }
    static func leagues() -> Endpoint<LeagueCatalog> { Endpoint("GET", "/leagues", authorized: false) }
    static func teams(_ league: String) -> Endpoint<TeamCatalog> {
        Endpoint("GET", "/leagues/\(segment(league))/teams", authorized: false)
    }
    static func stocks(_ query: String) -> Endpoint<StockSearch> {
        Endpoint("GET", "/stocks", query: [("q", query)], authorized: false, timeout: 8)
    }
}
