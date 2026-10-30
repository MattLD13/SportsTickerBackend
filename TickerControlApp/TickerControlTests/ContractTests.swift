import Foundation
import Testing
@testable import TickerControlCore

@MainActor
struct ContractTests {
    @Test func displayResponseDecodes() throws {
        let data = try JSONDecoder().decode(DisplayData.self, from: fixture("display-response"))
        #expect(!data.settings.mode.isEmpty)
        #expect(data.meta.pairing?.paired == false)
        #expect(data.meta.schedule != nil)
    }

    @Test func sportsFixtureKeepsEveryItemIdentity() throws {
        let data = try JSONDecoder().decode(DisplayData.self, from: fixture("display/sports"))
        #expect(!data.items.isEmpty)
        let identifiers = Set(data.content.values.flatMap { $0 }.map(\.id))
        #expect(data.items.allSatisfy { identifiers.contains($0.id) })
        #expect(data.items.first?.game != nil)
    }

    @Test func settingsResponseDecodesEveryServerField() throws {
        let settings = try JSONDecoder().decode(DisplaySettings.self, from: fixture("display-settings-response"))
        #expect(settings.mode == "pairing")
        #expect(settings.airportCodeICAO == "KEWR")
        #expect(settings.liveDelaySeconds == 45)
        #expect(settings.scrollSpeed == 0.03)
        #expect(settings.scoreAlerts)
        let empty = try JSONDecoder().decode(DisplaySettings.self, from: Data("{}".utf8))
        #expect(empty == DisplaySettings())
    }

    @Test func everyContentFamilyGetsItsTypedPayload() throws {
        let json = """
        {"settings":{"mode":"sports"},"meta":{},"content":{
          "sports":[{"id":"nhl-1","family":"sports","kind":"scoreboard","is_shown":true,
            "data":{"sport":"nhl","status":"OT","competition_stage":2,"home_abbr":"NYR","home_score":3,"away_abbr":"BOS","away_score":"2",
              "situation":{"powerPlay":true,"activeTeam":"NYR","shootout":{"away":["goal"],"home":["miss"]}}}}],
          "stock":[{"id":"stock:AAPL","family":"stock","kind":"stock_ticker","is_shown":true,
            "data":{"type":"stock_ticker","sport":"stock","symbol":"AAPL","home_abbr":"AAPL","home_score":"212.48","away_score":"-1.25%",
              "situation":{"change":"-2.62"},"status":"Tech"}}],
          "weather":[{"id":"weather","family":"weather","kind":"weather","is_shown":true,
            "data":{"type":"weather","city":"Bethlehem","temperature":72,"status":"SUNNY","feels":70,"wind":12,"humidity":68,
              "forecast":[{"day":"TODAY","icon":"sun","high":74,"low":66,"pop":0}]}}],
          "music":[{"id":"spotify:1","family":"music","kind":"spotify","is_shown":true,
            "data":{"type":"music","name":"Mr. Blue Sky","artist":"ELO","is_playing":true,"progress":78,"duration":303}}],
          "flights":[{"id":"UA123","family":"flights","kind":"flight_visitor","is_shown":true,
            "data":{"type":"flight_visitor","guest_name":"Mom","status":"EN ROUTE","is_live":true,"delay_min":20,"progress":55.4}}],
          "airports":[{"id":"airport:EWR","family":"airports","kind":"flight_airport_hud","is_shown":true,
            "data":{"type":"flight_airport_hud","weather":{"iata":"EWR","city":"Newark","away_abbr":"72F","status":"CLEAR"},
              "arrivals":[{"flight_number":"UA123","airport_code":"LAX","airport_city":"Los Angeles","status":"ARRIVING"}],"departures":[]}}],
          "clock":[{"id":"clock","family":"clock","kind":"clock","is_shown":true,"data":{"sport":"clock"}}],
          "status":[{"id":"ad","family":"sports","kind":"fan_duel_joke_ad","is_shown":true,"data":{"type":"fan_duel_joke_ad"}}]
        }}
        """
        let data = try JSONDecoder().decode(DisplayData.self, from: Data(json.utf8))
        let items = Dictionary(uniqueKeysWithValues: data.items.map { ($0.id, $0.payload) })
        #expect(items["ad"] == nil, "a campaign card is not a feed item")
        guard case .game(let game)? = items["nhl-1"], case .stock(let stock)? = items["stock:AAPL"],
              case .weather(let weather)? = items["weather"], case .music(let music)? = items["spotify:1"],
              case .flight(let flight)? = items["UA123"], case .airport(let airport)? = items["airport:EWR"],
              case .clock? = items["clock"] else { Issue.record("payload types: \(items)"); return }
        #expect(game.competitionStage == 2)
        #expect(game.home.score == "3")
        #expect(game.away.score == "2")
        #expect(game.situation?.powerPlay == true)
        #expect((game.situation?.shootout?.home ?? []) == ["miss"])
        #expect(stock.symbol == "AAPL")
        #expect(stock.price == "212.48")
        #expect(!stock.isUp)
        #expect(stock.changeAmount == "-2.62")
        #expect(weather.city == "Bethlehem")
        #expect(weather.temperature == "72")
        #expect(weather.forecast.first?.high == "74")
        #expect(music.title == "Mr. Blue Sky")
        #expect(music.isPlaying)
        #expect(abs(music.fraction - 78.0 / 303) < 0.0001)
        #expect(flight.delayed)
        #expect(flight.progress == 55)
        #expect(airport.code == "EWR")
        #expect(airport.arrivals.first?.number == "UA123")
        #expect(airport.arrivals.first?.city == "Los Angeles")
        #expect(airport.departures.isEmpty)
    }

    @Test func hardwareProfileDecodes() throws {
        let profile = try JSONDecoder().decode(TickerProfile.self, from: fixture("hardware-profile-response"))
        #expect(profile.display.width > 0)
        #expect(profile.capabilities.modes.contains("sports"))
    }

    @Test func tickerRecordReadsDeviceModesBeforeProfileModes() throws {
        let json = """
        {"ticker_id":"t1","name":"Kitchen","display_settings":{"brightness":40},
         "device":{"last_seen_at":12,"metadata":{"capabilities":["SPORTS"]}},
         "profile":{"product_family":"mini","hardware":"esp32-s3","firmware":"mini-2.0.0",
          "display":{"width":64,"height":32,"panel_count":1},
          "capabilities":{"modes":["sports","clock"],"asset_cache":true,"ota":true,"color_depth":16}}}
        """
        let ticker = try JSONDecoder().decode(TickerRecord.self, from: Data(json.utf8))
        #expect(ticker.settings.brightness == 40)
        #expect(ticker.modes == ["sports"])
        #expect(ticker.isSportsOnly)
        #expect(ticker.schedulableModes == ["sports", "clock"])
        #expect(ticker.profile?.displayName == "Ticker Mini")
    }

    @Test func scheduleResponsesDecode() throws {
        let schedule = try JSONDecoder().decode(Schedule.self, from: fixture("schedule-response"))
        #expect(schedule.effective.hasEnabledRules)
        #expect(!schedule.blocks.isEmpty)
        let status = try JSONDecoder().decode(ScheduleStatus.self, from: fixture("schedule-status-response"))
        #expect(!status.hasEnabledRules)
        let block = try JSONDecoder().decode(ScheduleBlock.self, from: fixture("schedule-block-response"))
        #expect(!block.daysOfWeek.isEmpty)
        _ = try JSONDecoder().decode(ScheduleCondition.self, from: fixture("schedule-condition-response"))
    }

    @Test func blockDraftMatchesTheRequestFixture() throws {
        let expected = try JSONSerialization.jsonObject(with: fixture("schedule-block-request")) as! [String: Any]
        let draft = ScheduleBlockDraft(daysOfWeek: expected["days_of_week"] as! [Int], startMinute: expected["start_minute"] as! Int,
                                       endMinute: expected["end_minute"] as! Int, mode: expected["mode"] as! String,
                                       sportsFilter: expected["sports_filter"] as? String, enabled: expected["enabled"] as? Bool ?? true)
        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(draft)) as! [String: Any]
        #expect(Set(encoded.keys).subtracting(["enabled", "sports_filter"]) == Set(expected.keys).subtracting(["enabled", "sports_filter"]))
        #expect((encoded["mode"] as? String) == (expected["mode"] as? String))
    }
}
