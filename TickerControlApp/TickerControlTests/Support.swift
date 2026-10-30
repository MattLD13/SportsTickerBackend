import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import Testing
@testable import TickerControlCore

/// Read a contract fixture from `docs/contracts/fixtures`.
func fixture(_ name: String) throws -> Data {
    let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    return try Data(contentsOf: repository.appendingPathComponent("docs/contracts/fixtures/\(name).json"))
}

func repositoryFile(_ path: String) throws -> String {
    let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    return try String(contentsOf: repository.appendingPathComponent(path), encoding: .utf8)
}

/// A server in memory. Each route answers from `routes`, and every request is recorded.
@MainActor
final class FakeServer: HTTPTransport {
    struct Answer { var status = 200; var body: Any = [String: Any]() }
    var routes: [String: Answer] = [:]
    private(set) var requests: [URLRequest] = []
    /// Requests wait until `release()` while `held` is true.
    var held = false
    private var waiting: [CheckedContinuation<Void, Never>] = []

    func on(_ method: String, _ path: String, status: Int = 200, _ body: Any = [String: Any]()) {
        routes["\(method) \(path)"] = Answer(status: status, body: body)
    }

    func release() {
        held = false
        let continuations = waiting
        waiting = []
        continuations.forEach { $0.resume() }
    }

    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        requests.append(request)
        if held { await withCheckedContinuation { waiting.append($0) } }
        let key = "\(request.httpMethod ?? "GET") \(request.url?.path ?? "")"
        let answer = routes[key] ?? Answer(status: 404, body: ["error": ["code": "not_found", "message": "no route \(key)"]])
        let data = try JSONSerialization.data(withJSONObject: answer.body)
        return (data, HTTPURLResponse(url: request.url!, statusCode: answer.status, httpVersion: nil, headerFields: nil)!)
    }

    func body(_ request: URLRequest) -> [String: Any] {
        request.httpBody.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
    }

    func sent(_ method: String, _ path: String) -> [URLRequest] {
        requests.filter { $0.httpMethod == method && $0.url?.path == path }
    }
}

@MainActor
final class MemoryValues: ValueStore {
    var values: [String: Any] = [:]
    func string(forKey key: String) -> String? { values[key] as? String }
    func stringArray(forKey key: String) -> [String]? { values[key] as? [String] }
    func set(_ value: Any?, forKey key: String) { values[key] = value }
}

@MainActor
final class MemoryCredentials: CredentialStore {
    var secrets: [String: String] = [:]
    var failsWrites = false
    func read(service: String, account: String) -> String? { secrets["\(service)|\(account)"] }
    func write(_ value: String, service: String, account: String) -> Bool {
        guard !failsWrites else { return false }
        secrets["\(service)|\(account)"] = value
        return true
    }
    func remove(service: String, account: String) { secrets["\(service)|\(account)"] = nil }
}

@MainActor
final class FakePlatform: TickerPlatform {
    var place = Place(name: "Boston", latitude: 42.36, longitude: -71.06)
    var provisioningCode: String? = "123456"
    func geocode(_ query: String) async throws -> Place {
        guard query != "nowhere" else { throw PlatformError("not found") }
        return place
    }
    func currentWiFiName() async throws -> String { "Home" }
    func provisionWiFi(code: String, ssid: String, password: String) async throws -> String? { provisioningCode }
    func cancelProvisioning() {}
    func authorizeSpotify(_ url: URL, callbackScheme: String) async throws -> URL {
        URL(string: "\(callbackScheme)://spotify?attempt_id=a1&status=connected")!
    }
}

/// A store on a fake server with one paired ticker, "t1".
@MainActor
struct Harness {
    let server = FakeServer()
    let values = MemoryValues()
    let credentials = MemoryCredentials()
    let platform = FakePlatform()
    let store: TickerStore

    init(paired: [String] = ["t1"], active: String? = "t1") {
        values.values["serverURL"] = "https://ticker.example"
        if let active { values.values["latchedTickerID"] = active }
        let session = Session(values: values, credentials: credentials)
        for id in paired { _ = session.saveToken("token-\(id)", for: id) }
        store = TickerStore(session: session, transport: server, platform: platform)
    }

    static func data(mode: String = "sports", items: [[String: Any]] = [], settings: [String: Any] = [:]) -> [String: Any] {
        var values: [String: Any] = ["mode": mode, "sports_filter": "all", "my_teams": ["nfl:NYG"], "weather_city": "Newark"]
        values.merge(settings) { _, new in new }
        return ["settings": values, "content": ["sports": items], "meta": ["pairing": ["paired": true]]]
    }

    static func game(_ id: String, shown: Bool = true, state: String = "pre") -> [String: Any] {
        ["id": id, "family": "sports", "kind": "scoreboard", "is_shown": shown,
         "data": ["sport": "nfl", "status": "Q1", "state": state, "home_abbr": "NYG", "away_abbr": "DAL", "home_score": 7, "away_score": "3"]]
    }

    static func ticker(_ id: String, modes: [String] = []) -> [String: Any] {
        ["ticker_id": id, "name": "Ticker \(id)", "display_settings": ["brightness": 80],
         "device": ["last_seen_at": 1_800_000_000, "metadata": ["capabilities": modes]]]
    }
}
