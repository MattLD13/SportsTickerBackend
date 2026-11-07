import Foundation

struct TickerDisplayResponse: Sendable {
    let response: V2DataResponse

    init(data: Data) throws {
        response = try JSONDecoder().decode(V2DataResponse.self, from: data)
    }

    func orderedGames(pinnedIDs: [String]) -> [Game] {
        let sports = response.settings.mode == "sports"
        let pins = Set(pinnedIDs)
        return response.games.enumerated()
            .filter { $0.element.is_shown || sports }
            .sorted { left, right in
                let first = left.element
                let second = right.element
                let firstPinned = pins.contains(first.id.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
                let secondPinned = pins.contains(second.id.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
                if firstPinned != secondPinned { return firstPinned }
                if first.is_shown != second.is_shown { return first.is_shown }
                if first.type == "stock_ticker" && second.type != "stock_ticker" { return true }
                if first.state == "in" && second.state != "in" { return true }
                return left.offset < right.offset
            }
            .map(\.element)
    }
}
