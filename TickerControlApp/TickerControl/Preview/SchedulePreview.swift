#if DEBUG
import Foundation
import SwiftUI

/// The schedule screens with the production store and views, served by an in-memory server.
/// The UI tests start the app with `-schedulePreview` and these options:
/// `-scheduleHomePreview` shows Home, `-emptySchedulePreview` starts without blocks,
/// `-singleDaySchedulePreview` puts the weather block on Monday only, `-scheduleReadFailure` fails the first read,
/// `-scheduleWriteFailure` fails every block write, and `-homeOverrideFailure` fails the Home override.
struct SchedulePreview: View {
    static let tickerID = "schedule-preview"
    static var isRequested: Bool { arguments.contains("-schedulePreview") }
    private static var arguments: [String] { ProcessInfo.processInfo.arguments }

    static func store() -> TickerStore {
        let values = PreviewValues()
        values.set(tickerID, forKey: "latchedTickerID")
        let session = Session(values: values, credentials: PreviewCredentials())
        return TickerStore(session: session, transport: PreviewServer(arguments: arguments), platform: PreviewPlatform())
    }

    @Environment(TickerStore.self) private var store

    var body: some View {
        Group {
            if Self.arguments.contains("-scheduleHomePreview") {
                HomeView()
                    .background(AppBackground())
                    .task {
                        await store.refreshDevices()
                        await store.refreshData()
                    }
            } else {
                ScheduleView(ticker: TickerRecord(id: Self.tickerID, name: "Living room ticker"))
            }
        }
        .preferredColorScheme(.dark)
    }
}

private final class PreviewValues: ValueStore {
    private var values: [String: Any] = [:]
    func string(forKey key: String) -> String? { values[key] as? String }
    func stringArray(forKey key: String) -> [String]? { values[key] as? [String] }
    func set(_ value: Any?, forKey key: String) { values[key] = value }
}

private final class PreviewCredentials: CredentialStore {
    func read(service: String, account: String) -> String? { "preview-only" }
    func write(_ value: String, service: String, account: String) -> Bool { true }
    func remove(service: String, account: String) {}
}

private final class PreviewPlatform: TickerPlatform {
    private static let unavailable = PlatformError("The schedule preview has no phone services.")
    func geocode(_ query: String) async throws -> Place { throw Self.unavailable }
    func currentWiFiName() async throws -> String { throw Self.unavailable }
    func provisionWiFi(code: String, ssid: String, password: String) async throws -> String? { throw Self.unavailable }
    func cancelProvisioning() {}
    func authorizeSpotify(_ url: URL, callbackScheme: String) async throws -> URL { throw Self.unavailable }
}

/// Serves the schedule routes of `docs/api.md` from memory. Enabled blocks cannot overlap, as on the server.
private final class PreviewServer: HTTPTransport {
    private var blocks: [[String: Any]]
    private var conditions: [[String: Any]] = []
    private var paused = false
    private var failRead: Bool
    private let failWrites: Bool
    private let failOverride: Bool
    private var created = 0

    init(arguments: [String]) {
        failRead = arguments.contains("-scheduleReadFailure")
        failWrites = arguments.contains("-scheduleWriteFailure")
        failOverride = arguments.contains("-homeOverrideFailure")
        if arguments.contains("-emptySchedulePreview") {
            blocks = []
        } else {
            blocks = [
                Self.block("weather", days: Array(0...4), start: 480, end: 540),
                Self.block("stock", days: Array(0...4), start: 540, end: 720),
                Self.block("clock", days: Array(0...4), start: 720, end: 780),
                Self.block("sports", days: Array(0...4), start: 1080, end: 1440),
                Self.block("music", days: [5, 6], start: 600, end: 840),
            ]
        }
        if arguments.contains("-singleDaySchedulePreview"), let index = blocks.firstIndex(where: { $0["id"] as? String == "weather" }) {
            blocks[index]["days_of_week"] = [0]
        }
    }

    private static func block(_ mode: String, days: [Int], start: Int, end: Int) -> [String: Any] {
        ["id": mode, "days_of_week": days, "start_minute": start, "end_minute": end, "mode": mode,
         "sports_filter": mode == "sports" ? "all" as Any : NSNull(), "enabled": true]
    }

    private var effective: [String: Any] {
        let enabled = (blocks + conditions).contains { $0["enabled"] as? Bool == true }
        return ["has_enabled_rules": enabled, "active": !paused, "override": paused, "source": paused ? "app_override" : "time",
                "override_expires_at": paused ? Date().timeIntervalSince1970 + 3600 as Any : NSNull(),
                "timezone": "America/New_York"]
    }

    private var ticker: [String: Any] {
        ["ticker_id": SchedulePreview.tickerID, "name": "Living room ticker", "display_settings": [:], "device": [:]]
    }

    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (object, status) = respond(request)
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
        return (try JSONSerialization.data(withJSONObject: object), response)
    }

    private func failure(_ message: String, _ status: Int) -> ([String: Any], Int) {
        (["error": ["code": "preview", "message": message]], status)
    }

    private func respond(_ request: URLRequest) -> ([String: Any], Int) {
        let path = request.url?.path ?? ""
        let method = request.httpMethod ?? "GET"
        let body = request.httpBody.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
        let ticker = "/tickers/\(SchedulePreview.tickerID)"
        switch (method, path) {
        case ("GET", "\(ticker)/schedule"):
            if failRead {
                failRead = false
                return failure("Preview connection interrupted. Try again.", 503)
            }
            return (["timezone": "America/New_York", "blocks": blocks, "conditions": conditions, "live_games": 3, "effective": effective], 200)
        case ("GET", "\(ticker)/data"):
            return (["settings": ["mode": "sports", "sports_filter": "all"], "content": [:], "meta": ["schedule": effective]], 200)
        case ("PATCH", ticker):
            guard let enabled = body["schedule_override"] as? Bool else { return (self.ticker, 200) }
            if failOverride { return failure("The server could not change the schedule.", 503) }
            paused = enabled
            return (self.ticker, 200)
        case ("GET", "/tickers"):
            return (["tickers": [self.ticker]], 200)
        case ("GET", "/leagues"):
            return (["leagues": []], 200)
        case ("GET", "/modes"):
            return (["modes": []], 200)
        case ("GET", "\(ticker)/spotify"):
            return (["connected": false, "status": "none", "accounts": []], 200)
        case (_, let route) where route.hasPrefix("\(ticker)/schedule/blocks"):
            if failWrites { return failure("enabled schedule blocks cannot overlap", 400) }
            if method != "DELETE", body["enabled"] as? Bool == true, overlaps(body, id: route.components(separatedBy: "/").last ?? "") {
                return failure("enabled schedule blocks cannot overlap", 400)
            }
            return change(&blocks, path: route, method: method, body: body)
        case (_, let route) where route.hasPrefix("\(ticker)/schedule/conditions"):
            return change(&conditions, path: route, method: method, body: body)
        default:
            return failure("The schedule preview does not serve \(method) \(path).", 404)
        }
    }

    private func overlaps(_ body: [String: Any], id: String) -> Bool {
        let days = Set(body["days_of_week"] as? [Int] ?? [])
        let start = body["start_minute"] as? Int ?? 0
        let end = body["end_minute"] as? Int ?? 0
        return blocks.contains { other in
            other["id"] as? String != id && other["enabled"] as? Bool == true
                && !days.isDisjoint(with: other["days_of_week"] as? [Int] ?? [])
                && start < (other["end_minute"] as? Int ?? 0) && end > (other["start_minute"] as? Int ?? 0)
        }
    }

    private func change(_ rows: inout [[String: Any]], path: String, method: String, body: [String: Any]) -> ([String: Any], Int) {
        let id = path.components(separatedBy: "/").last ?? ""
        switch method {
        case "DELETE":
            rows.removeAll { $0["id"] as? String == id }
            return ([:], 200)
        case "PATCH":
            guard let index = rows.firstIndex(where: { $0["id"] as? String == id }) else { return failure("Not found.", 404) }
            rows[index].merge(body) { _, new in new }
            return (rows[index], 200)
        default:
            created += 1
            var row = body
            row["id"] = "new-\(created)"
            rows.append(row)
            return (row, 201)
        }
    }
}
#endif
