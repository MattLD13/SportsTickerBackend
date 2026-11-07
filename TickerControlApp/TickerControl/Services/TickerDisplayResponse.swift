import Foundation

struct TickerDisplayResponse: Sendable {
    let response: V2DataResponse

    init(data: Data) throws {
        response = try JSONDecoder().decode(V2DataResponse.self, from: data)
    }

    func orderedGames(pinnedIDs: [String]) -> [Game] {
        let sports = response.settings.mode == "sports"
        let pins = Set(pinnedIDs)
        let dateFormatter = ISO8601DateFormatter()
        let fractionalFormatter = ISO8601DateFormatter()
        fractionalFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        func startDate(_ game: Game) -> Date {
            guard let start = game.startTimeUTC else { return .distantFuture }
            let normalized = start.replacingOccurrences(
                of: #"T(\d{2}):(\d{2})(Z|[+-]\d{2}:\d{2})$"#,
                with: "T$1:$2:00$3", options: .regularExpression
            )
            return fractionalFormatter.date(from: normalized) ?? dateFormatter.date(from: normalized) ?? .distantFuture
        }
        return response.games.enumerated()
            .filter { $0.element.is_shown || sports }
            .sorted { left, right in
                let first = left.element
                let second = right.element
                let firstPinned = pins.contains(first.id.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
                let secondPinned = pins.contains(second.id.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
                if firstPinned != secondPinned { return firstPinned }
                if first.is_shown != second.is_shown { return first.is_shown }
                if (first.type == "stock_ticker") != (second.type == "stock_ticker") { return first.type == "stock_ticker" }
                if sports {
                    let firstFinal = first.state?.lowercased() == "post"
                    let secondFinal = second.state?.lowercased() == "post"
                    if firstFinal != secondFinal { return !firstFinal }
                    let firstStart = startDate(first)
                    let secondStart = startDate(second)
                    if firstStart != secondStart { return firstStart < secondStart }
                    let firstOrder = first.rotation_order ?? Int.max
                    let secondOrder = second.rotation_order ?? Int.max
                    if firstOrder != secondOrder { return firstOrder < secondOrder }
                }
                return left.offset < right.offset
            }
            .map(\.element)
    }
}
