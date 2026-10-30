import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import Testing
@testable import TickerControlCore

@MainActor
struct EndpointTests {
    private let client = APIClient(baseURL: " https://ticker.example/ ")

    private func request<R>(_ endpoint: Endpoint<R>) throws -> URLRequest { try client.request(endpoint, token: "secret") }

    private func json(_ request: URLRequest) throws -> [String: Any] {
        let body = try #require(request.httpBody)
        return try #require(JSONSerialization.jsonObject(with: body) as? [String: Any])
    }

    /// Each route of the app and catalog tables in `docs/api.md` has one client endpoint.
    @Test func everyAppRouteOfTheAPIDocumentHasAnEndpoint() throws {
        let draft = ScheduleBlockDraft(daysOfWeek: [0], startMinute: 0, endMinute: 60, mode: "clock", enabled: true)
        let condition = ScheduleConditionDraft(isNew: true, threshold: 3, comparison: "gt", enabled: true)
        let requests = try [
            request(API.pair(PairRequest(pairingCode: "1", controllerGroupID: nil, controllerGroupSecret: nil))),
            request(API.tickers()), request(API.ticker("t")), request(API.updateTicker("t", TickerChange(name: "x"))),
            request(API.deleteTicker("t")), request(API.data("t")), request(API.pairingCode("t")), request(API.unpair("t")),
            request(API.reboot("t")), request(API.acknowledgeEvent("t", event: "e")), request(API.schedule("t")),
            request(API.createBlock("t", draft)), request(API.updateBlock("t", block: "b", draft)), request(API.deleteBlock("t", block: "b")),
            request(API.createCondition("t", condition)), request(API.updateCondition("t", condition: "c", condition)),
            request(API.deleteCondition("t", condition: "c")), request(API.spotify("t")), request(API.unlinkSpotify("t")),
            request(API.spotifyLogin("t")), request(API.spotifyPriority("t", account: nil)), request(API.unlinkSpotify("t", account: "a")),
            request(API.modes()), request(API.leagues()), request(API.teams("l")), request(API.stocks("q")),
        ]
        let routes = Set(requests.map { "\($0.httpMethod!) \(template($0.url!.path))" })
        let document = try repositoryFile("docs/api.md")
        var documented = Set<String>()
        var inSection = false
        for line in document.split(separator: "\n") {
            if line.hasPrefix("## ") { inSection = line == "## App" || line == "## Catalog" }
            let cells = line.split(separator: "|").map { $0.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "`", with: "") }
            guard inSection, cells.count >= 2, ["GET", "POST", "PATCH", "DELETE"].contains(cells[0]) else { continue }
            let path = cells[1].components(separatedBy: "?")[0]
            if path == "/spotify/callback" { continue }  // Spotify opens this route in the browser.
            documented.insert("\(cells[0]) \(path)")
        }
        #expect(routes == documented)
    }

    /// Replace the path values of the test requests with the names of `docs/api.md`.
    private func template(_ path: String) -> String {
        path.replacingOccurrences(of: "/tickers/t", with: "/tickers/<id>")
            .replacingOccurrences(of: "/events/e/", with: "/events/<event_id>/")
            .replacingOccurrences(of: "/blocks/b", with: "/blocks/<block_id>")
            .replacingOccurrences(of: "/conditions/c", with: "/conditions/<condition_id>")
            .replacingOccurrences(of: "/spotify/a", with: "/spotify/<account_id>")
            .replacingOccurrences(of: "/leagues/l/", with: "/leagues/<league_id>/")
    }

    @Test func authorizedRequestsCarryTheControllerToken() throws {
        let request = try request(API.data("ticker one"))
        #expect(request.url?.absoluteString == "https://ticker.example/tickers/ticker%20one/data")
        #expect(request.value(forHTTPHeaderField: "Authorization") == "Bearer secret")
        #expect(request.httpBody == nil)
        #expect(throws: APIError.notPaired) { try client.request(API.tickers(), token: nil) }
        let catalog = try client.request(API.leagues(), token: nil)
        #expect(catalog.value(forHTTPHeaderField: "Authorization") == nil)
        let search = try client.request(API.stocks("brk b"), token: nil)
        #expect(search.url?.query == "q=brk%20b")
        #expect(search.timeoutInterval == 8)
    }

    @Test func settingsPatchSendsOnlyItsFields() throws {
        let patch = DisplaySettingsPatch(brightness: 40, liveDelayMode: true)
        let body = try json(request(API.updateTicker("t", TickerChange(displaySettings: patch))))
        #expect(Set(body.keys) == ["display_settings"])
        let settings = try #require(body["display_settings"] as? [String: Any])
        #expect(Set(settings.keys) == ["brightness", "live_delay_mode"])
        let override = try json(request(API.updateTicker("t", TickerChange(scheduleOverride: false))))
        #expect((override as NSDictionary) == ["schedule_override": false])
        #expect(throws: EncodingError.self) { try JSONEncoder().encode(DisplaySettingsPatch(scrollSpeed: .nan)) }
    }

    @Test func displayPatchCarriesThePinOnlyWhilePinned() throws {
        var settings = DisplaySettings()
        settings.pinnedContentID = "game-1"
        settings.sportsPresentation = "rotation"
        #expect(DisplaySettingsPatch.display(settings, timezone: "UTC").pinnedContentID == "")
        settings.sportsPresentation = "pinned"
        let patch = DisplaySettingsPatch.display(settings, timezone: "UTC")
        #expect(patch.pinnedContentID == "game-1")
        #expect(patch.sportsPresentation == "pinned")
        #expect(patch.brightness == nil, "display edits leave the hardware settings alone")
    }

    @Test func draftsSendExplicitValues() throws {
        let block = ScheduleBlockDraft(daysOfWeek: [5, 6], startMinute: 600, endMinute: 840, mode: "music", sportsFilter: nil, enabled: false)
        let blockBody = try json(request(API.updateBlock("t", block: "b", block)))
        #expect(blockBody["sports_filter"] is NSNull, "a non-sports block clears its filter")
        #expect((blockBody["enabled"] as? Bool) == false)
        let new = try json(request(API.createCondition("t", ScheduleConditionDraft(isNew: true, threshold: 4, comparison: "gte", enabled: true))))
        #expect((new["kind"] as? String) == "live_games")
        #expect((new["operator"] as? String) == "gte")
        #expect((new["action_sports_filter"] as? String) == "live")
        let changed = try json(request(API.updateCondition("t", condition: "c", ScheduleConditionDraft(isNew: false, threshold: 4, comparison: "gt", enabled: true))))
        #expect(changed["kind"] == nil)
        let priority = try json(request(API.spotifyPriority("t", account: nil)))
        #expect(priority["spotify_account_id"] is NSNull)
    }

    @Test func serverErrorsKeepTheirCodeAndBoundedMessage() async throws {
        let server = FakeServer()
        server.on("GET", "/tickers", status: 403, ["error": ["code": "forbidden", "message": "  Pair this ticker again.  "]])
        let api = APIClient(baseURL: "https://ticker.example", transport: server)
        do {
            _ = try await api.send(API.tickers(), token: "t")
            Issue.record("the request must fail")
        } catch let error as APIError {
            #expect(error == .server(status: 403, code: "forbidden", message: "Pair this ticker again."))
            #expect(error.localizedDescription == "The server rejected the request (HTTP 403). Pair this ticker again.")
        }
        let long = try JSONSerialization.data(withJSONObject: ["error": ["message": String(repeating: "x", count: 500)]])
        guard case .server(_, _, let message) = APIError.server(status: 500, body: long) else { Issue.record("unexpected error"); return }
        #expect(message?.count == 200)
        guard case .server(_, nil, nil) = APIError.server(status: 502, body: Data("<html>".utf8)) else { Issue.record("unexpected error"); return }
    }

    @Test func invalidServerURLFailsBeforeSending() {
        let api = APIClient(baseURL: "not a url")
        #expect(throws: APIError.invalidServerURL) { try api.request(API.leagues(), token: nil) }
    }
}
