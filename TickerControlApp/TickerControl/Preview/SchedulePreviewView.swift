#if DEBUG
import SwiftUI

// This preview uses the production views and request code with an in-memory transport.
struct SchedulePreviewView: View {
    @StateObject private var vm = TickerViewModel(
        httpClient: SchedulePreviewTransport(), credentialStore: SchedulePreviewCredentials())
    @State private var presented = true

    var body: some View {
        Group {
          if ProcessInfo.processInfo.arguments.contains("-scheduleHomePreview") {
            HomeView(vm: vm)
                .background(LinearGradient(colors: [Color(red: 0.22, green: 0.28, blue: 0.35),
                    Color(red: 0.05, green: 0.07, blue: 0.10)], startPoint: .top, endPoint: .bottom).ignoresSafeArea())
                .onAppear {
                    vm.devices = [device]
                    vm.switchToTicker(device.id)
                    vm.fetchData()
                }
          } else {
            TickerScheduleView(vm: vm, device: device, isPresented: $presented)
          }
        }.preferredColorScheme(.dark)
    }

    private var device: TickerDevice {
        TickerDevice(
            id: "schedule-preview", name: "Living room ticker",
            settings: DeviceSettings(brightness: 80, scroll_speed: 0.03),
            last_seen: nil, capabilities: [], profile: nil)
    }
}

private final class SchedulePreviewCredentials: TickerCredentialStore {
    func read(service: String, account: String) -> String? { "preview-only" }
    func write(_ value: String, service: String, account: String) -> Bool { true }
    func remove(service: String, account: String) {}
}

private final class SchedulePreviewTask: TickerHTTPTask {
    private var action: (() -> Void)?
    init(_ action: @escaping () -> Void) { self.action = action }
    func resume() { action?(); action = nil }
    func cancel() { action = nil }
}

private final class SchedulePreviewTransport: TickerHTTPTransport {
    private var blocks: [[String: Any]]
    private var conditions: [[String: Any]] = []
    private var manual = false
    private var failedRead = false
    private var mutationNumber = 0
    private var effective: [String: Any] {
        let expiry: Any = manual ? (Date().timeIntervalSince1970 + 3600) as Any : NSNull()
        return ["active": !manual, "override": manual, "source": manual ? "app_override" : "time",
         "override_expires_at": expiry,
         "timezone": "America/New_York"]
    }

    init() {
        let arguments = ProcessInfo.processInfo.arguments
        failedRead = arguments.contains("-scheduleReadFailure")
        if arguments.contains("-emptySchedulePreview") {
            blocks = []
        } else {
            blocks = [
                Self.block("weather", days: Array(0...4), start: 480, end: 540, mode: "weather"),
                Self.block("stock", days: Array(0...4), start: 540, end: 720, mode: "stock"),
                Self.block("clock", days: Array(0...4), start: 720, end: 780, mode: "clock"),
                Self.block("sports", days: Array(0...4), start: 1080, end: 1440, mode: "sports"),
                Self.block("music", days: [5, 6], start: 600, end: 840, mode: "music"),
            ]
        }
        if arguments.contains("-singleDaySchedulePreview"), let index = blocks.firstIndex(where: { $0["id"] as? String == "weather" }) {
            blocks[index]["days_of_week"] = [0]
        }
    }

    private static func block(_ id: String, days: [Int], start: Int, end: Int, mode: String) -> [String: Any] {
        let filter: Any = mode == "sports" ? "all" as Any : NSNull()
        return ["id": id, "ticker_id": "schedule-preview", "days_of_week": days, "day_names": [],
         "start_minute": start, "end_minute": end, "mode": mode, "sports_filter": filter,
         "enabled": true, "created_at": 0, "updated_at": 0]
    }

    func dataTask(with request: URLRequest) -> any TickerHTTPTask {
        dataTask(with: request) { _, _, _ in }
    }

    func dataTask(with request: URLRequest, completionHandler: @escaping TickerHTTPCompletion) -> any TickerHTTPTask {
        SchedulePreviewTask {
            let (object, status) = self.response(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)
            let data = try? JSONSerialization.data(withJSONObject: object)
            completionHandler(data, response, nil)
        }
    }

    private func response(_ request: URLRequest) -> ([String: Any], Int) {
        let path = request.url?.path ?? ""
        let method = request.httpMethod ?? "GET"
        let body = request.httpBody.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
        if path.hasSuffix("/schedule"), method == "GET" {
            if failedRead {
                failedRead = false
                return (["error": ["message": "Preview connection interrupted. Try again."]], 503)
            }
            return (["api_version": "2", "ticker_id": "schedule-preview", "timezone": "America/New_York",
                     "days": [], "blocks": blocks, "conditions": conditions, "live_games": 3,
                     "effective": effective], 200)
        }
        if path.hasSuffix("/data") {
            return (["settings": ["mode": "sports", "sports_filter": "all"], "content": [:],
                     "meta": ["schedule": effective]], 200)
        }
        if path.contains("/schedule/blocks"), method != "GET" {
            if ProcessInfo.processInfo.arguments.contains("-scheduleWriteFailure") {
                return (["error": ["message": "enabled schedule blocks cannot overlap"]], 400)
            }
            if method != "DELETE", body["enabled"] as? Bool == true {
                let identifier = path.components(separatedBy: "/").last ?? ""
                let days = Set(body["days_of_week"] as? [Int] ?? [])
                let start = body["start_minute"] as? Int ?? 0
                let end = body["end_minute"] as? Int ?? 0
                let overlaps = blocks.contains { existing in
                    existing["id"] as? String != identifier && existing["enabled"] as? Bool == true &&
                    !days.isDisjoint(with: existing["days_of_week"] as? [Int] ?? []) &&
                    start < (existing["end_minute"] as? Int ?? 0) && end > (existing["start_minute"] as? Int ?? 0)
                }
                if overlaps { return (["error": ["message": "enabled schedule blocks cannot overlap"]], 400) }
            }
            return mutate(&blocks, path: path, method: method, body: body)
        }
        if path.contains("/schedule/conditions"), method != "GET" {
            return mutate(&conditions, path: path, method: method, body: body)
        }
        if let enabled = body["schedule_override"] as? Bool {
            if ProcessInfo.processInfo.arguments.contains("-homeOverrideFailure") {
                return (["error": ["message": "The server could not change the schedule."]], 503)
            }
            manual = enabled
            return ([:], 200)
        }
        if path.hasSuffix("/catalog/leagues") { return (["leagues": []], 200) }
        if path.hasSuffix("/catalog/modes") { return (["modes": []], 200) }
        if path.hasSuffix("/tickers") { return (["tickers": []], 200) }
        // Unrelated polling stays inside this transport and never reaches a live server.
        return ([:], 200)
    }

    private func mutate(_ rows: inout [[String: Any]], path: String, method: String,
                        body: [String: Any]) -> ([String: Any], Int) {
        let id = path.components(separatedBy: "/").last ?? ""
        if method == "DELETE" { rows.removeAll { $0["id"] as? String == id }; return ([:], 200) }
        if method == "PATCH", let index = rows.firstIndex(where: { $0["id"] as? String == id }) {
            rows[index].merge(body) { _, new in new }
            return (rows[index], 200)
        }
        mutationNumber += 1
        var row = body
        row.merge(["id": "new-\(mutationNumber)", "ticker_id": "schedule-preview", "day_names": [],
                   "created_at": 0, "updated_at": 0]) { _, new in new }
        rows.append(row)
        return (row, 201)
    }
}
#endif
