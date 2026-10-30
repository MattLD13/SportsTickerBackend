import Foundation

/// A league, a college conference, or a stock list of the catalog.
struct League: Decodable, Identifiable, Hashable {
    let id: String
    let label: String
    let type: String
    let myTeamsEnabled: Bool?
    let conferenceParent: String?
    enum CodingKeys: String, CodingKey { case id, label, type, myTeamsEnabled = "my_teams_enabled", conferenceParent = "conference_parent" }

    var isSport: Bool { type == "sport" }
    var isStockList: Bool { type == "stock" }
}

struct LeagueCatalog: Decodable { let leagues: [League] }

struct Team: Decodable, Identifiable, Hashable {
    let id: String
    let abbr: String
    let logo: String?

    /// The catalog has placeholder rows for teams that are not known yet.
    var isPlaceholder: Bool {
        let code = abbr.trimmingCharacters(in: .whitespaces)
        return code.isEmpty || code == "TBD" || code == "null"
    }
}

struct TeamCatalog: Decodable { let teams: [Team] }

struct ModeOption: Decodable { let id: String; let symbol: String }
struct ModeCatalog: Decodable { let modes: [ModeOption] }

struct StockSymbol: Codable, Identifiable, Equatable {
    let symbol: String
    let name: String
    var id: String { symbol }
}

struct StockSearch: Decodable { let stocks: [StockSymbol] }
