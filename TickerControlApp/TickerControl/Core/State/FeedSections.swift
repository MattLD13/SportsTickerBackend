import Foundation

/// The items of the Home feed, in display order and grouped by card type.
struct FeedSections {
    var games: [FeedItem] = []
    var music: [FeedItem] = []
    var stocks: [FeedItem] = []
    var weather: [FeedItem] = []
    var flights: [FeedItem] = []
    var airports: [FeedItem] = []

    init() {}

    init(_ items: [FeedItem]) {
        for item in items {
            switch item.payload {
            case .game, .clock: games.append(item)
            case .music: music.append(item)
            case .stock: stocks.append(item)
            case .weather: weather.append(item)
            case .flight: flights.append(item)
            case .airport: airports.append(item)
            }
        }
    }
}

enum FeedOrder {
    /// Order the feed: the pinned game, then shown items, then stocks, then live games, then server order.
    /// In Sports mode the feed also lists hidden games, so a user can pin any game.
    static func items(_ data: DisplayData, pinnedID: String?) -> [FeedItem] {
        let sports = data.settings.mode == "sports"
        return data.items.enumerated()
            .filter { $0.element.isShown || sports }
            .sorted { left, right in
                let first = left.element, second = right.element
                let firstPinned = first.pinID == pinnedID, secondPinned = second.pinID == pinnedID
                if firstPinned != secondPinned { return firstPinned }
                if first.isShown != second.isShown { return first.isShown }
                if first.isStock != second.isStock { return first.isStock }
                if first.isLive != second.isLive { return first.isLive }
                return left.offset < right.offset
            }
            .map(\.element)
    }
}

private extension FeedItem {
    var isStock: Bool { if case .stock = payload { return true } else { return false } }
}
