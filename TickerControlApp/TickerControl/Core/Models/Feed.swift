import Foundation

/// The data of one ticker, as `GET /tickers/<id>/data` returns it.
struct DisplayData: Decodable {
    let settings: DisplaySettings
    let content: [String: [FeedItem]]
    let meta: DisplayMeta

    /// Every item in family order. A campaign card is display content only, so the feed leaves it out.
    var items: [FeedItem] {
        let preferred = ["sports", "golf", "racing", "weather", "music", "flights", "airports", "clock", "status", "stock"]
        let families = preferred.filter(content.keys.contains) + content.keys.filter { !preferred.contains($0) }.sorted()
        return families.flatMap { content[$0, default: []] }.filter { !$0.isCampaign }
    }
}

struct DisplayMeta: Decodable {
    let pairing: PairingState?
    let schedule: ScheduleStatus?
}

struct PairingState: Decodable { let paired: Bool; let code: String? }

/// One content item. The payload is typed by the kind of the item.
struct FeedItem: Decodable, Identifiable {
    let id: String
    let family: String
    let kind: String
    let isShown: Bool
    let payload: Payload
    private let type: String

    enum Payload {
        case game(Game)
        case stock(StockQuote)
        case weather(WeatherReport)
        case music(NowPlaying)
        case flight(TrackedFlight)
        case airport(AirportBoard)
        case clock
    }

    private enum Keys: String, CodingKey { case id, family, kind, is_shown, data }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: Keys.self)
        id = try container.decode(String.self, forKey: .id)
        family = try container.decode(String.self, forKey: .family)
        kind = try container.decode(String.self, forKey: .kind)
        isShown = try container.decode(Bool.self, forKey: .is_shown)
        let data = try container.nestedContainer(keyedBy: FieldKey.self, forKey: .data)
        type = data.text("type") ?? kind
        let sport = data.text("sport") ?? family
        switch (type, sport) {
        case ("stock_ticker", _), (_, "stock"): payload = .stock(StockQuote(data))
        case ("weather", _), (_, "weather"): payload = .weather(WeatherReport(data))
        case ("music", _): payload = .music(NowPlaying(data))
        case ("flight_visitor", _): payload = .flight(TrackedFlight(data, id: id))
        case ("flight_airport_hud", _), (_, "airport"): payload = .airport(AirportBoard(data))
        case (_, "clock"): payload = .clock
        default: payload = .game(Game(data, family: family))
        }
    }

    var isCampaign: Bool { type == "fan_duel_joke_ad" }

    var game: Game? { if case .game(let game) = payload { return game } else { return nil } }

    var isLive: Bool { game?.state == "in" }

    /// The pin ID of a game, in the form the server stores in `pinned_content_id`.
    var pinID: String { id.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
}

struct TeamSide {
    let abbr: String
    let id: String?
    let score: String
    let logo: String?
    let color: String?
    let altColor: String?

    init(_ data: KeyedDecodingContainer<FieldKey>, side: String) {
        abbr = data.text("\(side)_abbr") ?? ""
        id = data.text("\(side)_id")
        score = data.text("\(side)_score") ?? "0"
        logo = data.text("\(side)_logo")
        color = data.text("\(side)_color")
        altColor = data.text("\(side)_alt_color")
    }
}

/// A game, a tournament, or a race: the content of the sports families.
struct Game {
    let sport: String
    let status: String
    let state: String?
    let competitionStage: Int?
    let away: TeamSide
    let home: TeamSide
    let situation: Situation?
    let tournament: String?

    init(_ data: KeyedDecodingContainer<FieldKey>, family: String) {
        sport = data.text("sport") ?? family
        status = data.text("status") ?? ""
        state = data.text("state")
        competitionStage = data.int("competition_stage")
        away = TeamSide(data, side: "away")
        home = TeamSide(data, side: "home")
        situation = data.object("situation").map(Situation.init)
        tournament = data.text("tourney_name")
    }

    func side(isHome: Bool) -> TeamSide { isHome ? home : away }
}

struct Situation {
    let activeTeam: String?
    let downDistance: String?
    let isRedZone: Bool
    let balls: Int?
    let strikes: Int?
    let outs: Int?
    let powerPlay: Bool
    let emptyNet: Bool
    let shootout: Shootout?

    struct Shootout { let away: [String]?; let home: [String]? }

    init(_ data: KeyedDecodingContainer<FieldKey>) {
        activeTeam = data.text("activeTeam")
        downDistance = data.text("downDist")
        isRedZone = data.bool("isRedZone") ?? false
        balls = data.int("balls")
        strikes = data.int("strikes")
        outs = data.int("outs")
        powerPlay = data.bool("powerPlay") ?? false
        emptyNet = data.bool("emptyNet") ?? false
        shootout = data.object("shootout").map { Shootout(away: $0.value([String].self, "away"), home: $0.value([String].self, "home")) }
    }
}

/// A stock quote. The server sends the price in `home_score` and the change in percent in `away_score`.
struct StockQuote {
    let symbol: String
    let price: String
    let changePercent: String
    let changeAmount: String
    let logo: String?
    let list: String

    init(_ data: KeyedDecodingContainer<FieldKey>) {
        symbol = data.text("symbol") ?? data.text("home_abbr") ?? ""
        price = data.text("home_score") ?? ""
        changePercent = data.text("away_score") ?? ""
        changeAmount = data.object("situation")?.text("change") ?? ""
        logo = data.text("home_logo")
        list = data.text("status") ?? ""
    }

    var isUp: Bool { !changePercent.contains("-") }
}

struct WeatherReport {
    let city: String
    let temperature: String
    let condition: String
    let icon: String?
    let feels: String?
    let wind: String?
    let humidity: String?
    let forecast: [ForecastDay]

    struct ForecastDay {
        let day: String?
        let icon: String?
        let high: String?
        let low: String?
        let precipitation: String?
    }

    init(_ data: KeyedDecodingContainer<FieldKey>) {
        city = data.text("city") ?? ""
        temperature = data.text("temperature") ?? ""
        condition = data.text("status") ?? ""
        icon = data.text("icon")
        feels = data.text("feels")
        wind = data.text("wind")
        humidity = data.text("humidity")
        forecast = data.objects("forecast") {
            ForecastDay(day: $0.text("day"), icon: $0.text("icon"), high: $0.text("high"), low: $0.text("low"), precipitation: $0.text("pop"))
        } ?? []
    }
}

struct NowPlaying {
    let title: String?
    let artist: String?
    let cover: String?
    let isPlaying: Bool
    let progress: Double?
    let duration: Double?

    init(_ data: KeyedDecodingContainer<FieldKey>) {
        title = data.text("name")
        artist = data.text("artist")
        cover = data.text("cover")
        isPlaying = data.bool("is_playing") ?? false
        progress = data.double("progress")
        duration = data.double("duration")
    }

    /// The played share of the track, from 0 to 1.
    var fraction: Double {
        guard let duration, duration > 0 else { return 0 }
        return min(max((progress ?? 0) / duration, 0), 1)
    }
}

struct TrackedFlight {
    let id: String
    let guestName: String?
    let route: String?
    let status: String
    let originCity: String?
    let destinationCity: String?
    let isLive: Bool
    let isDelayed: Bool
    let delayMinutes: Int?
    let progress: Int?
    let eta: String?

    init(_ data: KeyedDecodingContainer<FieldKey>, id: String) {
        self.id = id
        guestName = data.text("guest_name")
        route = data.text("route")
        status = data.text("status") ?? ""
        originCity = data.text("origin_city")
        destinationCity = data.text("dest_city")
        isLive = data.bool("is_live") ?? false
        isDelayed = data.bool("is_delayed") ?? false
        delayMinutes = data.int("delay_min")
        progress = data.int("progress")
        eta = data.text("eta_str")
    }

    /// A flight counts as delayed at 15 minutes.
    var delayed: Bool { isDelayed || (delayMinutes ?? 0) >= 15 }
}

struct AirportBoard {
    let code: String?
    let city: String?
    let temperature: String?
    let condition: String?
    let arrivals: [Flight]
    let departures: [Flight]

    struct Flight {
        let number: String?
        let airport: String?
        let city: String?
        let status: String?

        init(_ data: KeyedDecodingContainer<FieldKey>) {
            number = data.text("flight_number")
            airport = data.text("airport_code")
            city = data.text("airport_city")
            status = data.text("status")
        }
    }

    init(_ data: KeyedDecodingContainer<FieldKey>) {
        let weather = data.object("weather")
        code = weather?.text("iata")
        city = weather?.text("city")
        temperature = weather?.text("away_abbr")
        condition = weather?.text("status")
        arrivals = data.objects("arrivals", Flight.init) ?? []
        departures = data.objects("departures", Flight.init) ?? []
    }
}
