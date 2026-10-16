import SwiftUI
import Foundation
import Combine
import UIKit
import CoreLocation
import Security
import AuthenticationServices
import NetworkExtension
import CoreBluetooth
import CryptoKit

struct SituationPill: View {
    let text: String; let color: Color
    var body: some View {
        Text(text).font(.system(size: 10, weight: .black)).foregroundColor(color)
            .padding(.horizontal, 6).padding(.vertical, 3).background(color.opacity(0.2))
            .cornerRadius(4).overlay(RoundedRectangle(cornerRadius: 4).stroke(color.opacity(0.3), lineWidth: 1))
    }
}
struct FootballDownContext: View {
    let downDist: String?
    let isRedZone: Bool

    var body: some View {
        if let downDist, !downDist.isEmpty {
            SituationPill(text: downDist, color: isRedZone ? .red : .yellow)
        }
    }
}
struct BaseballCountContext: View {
    let balls: Int
    let strikes: Int
    let outs: Int

    var body: some View {
        HStack(spacing: 4) {
            HStack(spacing: 3) {
                count("B", value: balls, color: .green)
                count("S", value: strikes, color: .yellow)
                count("O", value: outs, color: .red)
            }
            .padding(.horizontal, 6).padding(.vertical, 3)
            .background(Color.white.opacity(0.12))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color.white.opacity(0.16), lineWidth: 1))
            .cornerRadius(4)
        }
    }

    @ViewBuilder private func count(_ label: String, value: Int, color: Color) -> some View {
        Text(label).font(.system(size: 8, weight: .black)).foregroundStyle(color)
        Text("\(value)").font(.system(size: 10, weight: .black)).foregroundStyle(.white)
    }
}
struct ShootoutBubbles: View {
    let results: [String]
    let maxDots: Int
    var body: some View {
        HStack(spacing: 2) {
            ForEach(0..<max(maxDots, results.count), id: \.self) { i in
                if i < results.count {
                    let res = results[i]
                    if res == "goal" {
                        Image(systemName: "checkmark.circle.fill").symbolRenderingMode(.palette).foregroundStyle(.white, .green).font(.system(size: 8))
                    } else if res == "miss" {
                        Image(systemName: "xmark.circle.fill").symbolRenderingMode(.palette).foregroundStyle(.white, .red).font(.system(size: 8))
                    } else {
                        Image(systemName: "circle").foregroundStyle(.gray).font(.system(size: 8))
                    }
                } else {
                    Image(systemName: "circle").foregroundStyle(.gray.opacity(0.5)).font(.system(size: 8))
                }
            }
        }
    }
}
struct TabButton: View {
    let icon: String; let label: String; let idx: Int; @Binding var sel: Int
    var body: some View { Button { sel = idx } label: { VStack(spacing: 4) { Image(systemName: icon).font(.system(size: 20)); Text(label).font(.caption2) }.frame(maxWidth: .infinity).foregroundColor(sel == idx ? .white : .gray).padding(.vertical, 8).background(sel == idx ? Color.white.opacity(0.15) : Color.clear).cornerRadius(12) } }
}
struct FilterBtn: View {
    let title: String; let val: String; let cur: String; let act: () -> Void
    var body: some View { Button(action: act) { Text(title).font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12).background(cur == val ? Color(red: 0.0, green: 0.47, blue: 1.0) : Color.white.opacity(0.05)).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous)).overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(cur == val ? Color.blue : Color.white.opacity(0.1), lineWidth: 1)).foregroundColor(.white) } }
}
struct ScrollBtn: View {
    let title: String; let val: Bool; let cur: Bool; let act: () -> Void
    var body: some View { Button(action: act) { Text(title).font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12).background(cur == val ? Color(red: 0.0, green: 0.47, blue: 1.0) : Color.white.opacity(0.05)).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous)).overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(cur == val ? Color.blue : Color.white.opacity(0.1), lineWidth: 1)).foregroundColor(.white) } }
}
struct TeamLogoView: View {
    let url: String?; let abbr: String; let size: CGFloat
    var body: some View { AsyncImage(url: URL(string: url ?? "")) { phase in if let image = phase.image { image.resizable().scaledToFit() } else { Text(abbr).font(.system(size: size * 0.4, weight: .bold)).foregroundColor(.white.opacity(0.8)) } }.frame(width: size, height: size) }
}
struct MusicNowPlayingCard: View {
    let game: Game

    private var isPlaying: Bool { game.status == "playing" }
    private var progress: Double {
        guard let duration = game.duration, duration > 0 else { return 0 }
        return min(max(Double(game.progress ?? 0) / duration, 0), 1)
    }

    var body: some View {
        HStack(spacing: 14) {
            AsyncImage(url: URL(string: game.cover ?? "")) { phase in
                if let image = phase.image {
                    image.resizable().scaledToFill()
                } else {
                    Image(systemName: "music.note")
                        .font(.title2).foregroundStyle(.green)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color.green.opacity(0.14))
                }
            }
            .frame(width: 58, height: 58)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Image(systemName: isPlaying ? "waveform" : "pause.fill")
                        .font(.caption).foregroundStyle(isPlaying ? .green : .secondary)
                    Text(isPlaying ? "NOW PLAYING" : "SPOTIFY")
                        .font(.caption2.weight(.bold)).foregroundStyle(isPlaying ? .green : .secondary)
                }
                Text(game.name ?? "No active Spotify playback")
                    .font(.headline).foregroundStyle(.white).lineLimit(1)
                Text(game.artist ?? "Choose an account in Music settings")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                ProgressView(value: progress)
                    .tint(.green).opacity(game.duration == nil ? 0 : 1)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(Color.green.opacity(isPlaying ? 0.55 : 0.2), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
struct StockFeedCard: View {
    let game: Game

    private var isUp: Bool { !game.away_score.contains("-") }
    private var changeColor: Color { isUp ? .green : .red }

    var body: some View {
        HStack(spacing: 14) {
            AsyncImage(url: URL(string: game.safeHomeLogo)) { phase in
                if let image = phase.image {
                    image.resizable().scaledToFit().padding(7)
                } else {
                    Text(game.safeHomeAbbr.prefix(4)).font(.caption.weight(.heavy))
                }
            }
            .frame(width: 54, height: 54)
            .background(changeColor.opacity(0.13))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))

            VStack(alignment: .leading, spacing: 5) {
                Text("MARKETS").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text(game.safeHomeAbbr).font(.headline).foregroundStyle(.white)
                Text(game.status.isEmpty ? "Live quote" : game.status)
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 5) {
                Text("$\(game.home_score)").font(.headline.weight(.bold)).foregroundStyle(.white)
                Label("\(game.situation?.change ?? "")  \(game.away_score)", systemImage: isUp ? "arrow.up.right" : "arrow.down.right")
                    .font(.caption2.weight(.bold)).foregroundStyle(changeColor)
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(changeColor.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
struct WeatherLocationCard: View {
    let game: Game

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: weatherIcon(for: game.status))
                .font(.system(size: 30)).foregroundStyle(.yellow)
                .frame(width: 54, height: 54)
                .background(Color.blue.opacity(0.15))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 5) {
                Text("LOCAL WEATHER").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text(game.safeAwayAbbr.isEmpty ? "Weather" : game.safeAwayAbbr)
                    .font(.headline).foregroundStyle(.white)
                Text(game.status.capitalized).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Text("NOW").font(.caption2.weight(.bold)).foregroundStyle(.blue)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.blue.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

}
struct WeatherCurrentCard: View {
    let game: Game

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: "thermometer.medium")
                .font(.system(size: 28)).foregroundStyle(.orange)
                .frame(width: 54, height: 54)
                .background(Color.orange.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 5) {
                Text("CURRENT TEMPERATURE").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text("Feels like \(game.feels ?? game.safeHomeAbbr)°")
                    .font(.headline).foregroundStyle(.white)
                Text(currentDetails).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Text("\(game.safeHomeAbbr)°")
                .font(.system(size: 30, weight: .bold, design: .rounded)).foregroundStyle(.white)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.orange.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private var currentDetails: String {
        [game.wind.map { "Wind \($0) mph" }, game.humidity.map { "Humidity \($0)%" }]
            .compactMap { $0 }.joined(separator: " · ")
    }
}
struct WeatherTodayCard: View {
    let game: Game

    private var today: WeatherForecast? { game.forecast?.first }

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: weatherIcon(for: today?.icon ?? game.status))
                .font(.system(size: 28)).foregroundStyle(.cyan)
                .frame(width: 54, height: 54)
                .background(Color.cyan.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 5) {
                Text("\(today?.day?.uppercased() ?? "TODAY") FORECAST")
                    .font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text("High \(today?.high ?? "—")°  ·  Low \(today?.low ?? "—")°")
                    .font(.headline).foregroundStyle(.white)
                Text(today?.pop.map { "\($0)% precipitation chance" } ?? "Forecast updating")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.cyan.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
struct TrackedFlightFeedCard: View {
    let game: Game

    private var active: Bool { game.is_live == true }
    private var delayed: Bool { game.is_delayed == true || (game.delay_min ?? 0) >= 15 }
    private var accent: Color { delayed ? .red : (active ? .orange : .secondary) }
    private var progress: Double { min(max(Double(game.progress ?? 0) / 100, 0), 1) }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 10) {
                Image(systemName: "airplane.circle.fill").font(.title2).foregroundStyle(accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(game.guest_name ?? game.id).font(.headline).foregroundStyle(.white)
                    Text(game.route ?? "Tracked flight").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Text(game.status.uppercased()).font(.caption2.weight(.bold)).foregroundStyle(accent)
            }
            HStack {
                Text(game.origin_city ?? "—").font(.caption.weight(.bold)).foregroundStyle(.white)
                Spacer()
                Image(systemName: "airplane").font(.caption).foregroundStyle(accent)
                Spacer()
                Text(game.dest_city ?? "—").font(.caption.weight(.bold)).foregroundStyle(.white)
            }
            ProgressView(value: progress).tint(accent).opacity(game.progress == nil ? 0 : 1)
            if let eta = game.eta_str, !eta.isEmpty {
                Text("ETA \(eta)").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(accent.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
struct AirportLocationCard: View {
    let game: Game

    private var airport: AirportWeather? { game.airportWeather }

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: "airplane.departure").font(.title2).foregroundStyle(.cyan)
                .frame(width: 54, height: 54)
                .background(Color.cyan.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text("AIRPORT ACTIVITY").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text(airport?.iata ?? "AIRPORT").font(.headline).foregroundStyle(.white)
                Text(airport?.city ?? "Live airport activity").font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            if let weather = airport, !weather.away_abbr.orEmpty.isEmpty {
                VStack(alignment: .trailing, spacing: 4) {
                    Image(systemName: weatherIcon(for: weather.status ?? "")).foregroundStyle(.cyan)
                    Text(weather.away_abbr ?? "").font(.caption.weight(.bold)).foregroundStyle(.white)
                }
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.cyan.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
struct AirportScheduleFeedCard: View {
    let title: String
    let icon: String
    let flights: [AirportFlight]
    let color: Color

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icon).font(.title2).foregroundStyle(color)
                .frame(width: 54, height: 54)
                .background(color.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.caption2.weight(.bold)).foregroundStyle(color)
                Text(flights.first?.home_abbr ?? "No scheduled flights")
                    .font(.headline).foregroundStyle(.white).lineLimit(1)
                Text(destinationText).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            Text("\(flights.count)").font(.title3.weight(.bold)).foregroundStyle(color)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(color.opacity(0.35), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private var destinationText: String {
        guard let first = flights.first else { return "Waiting for schedule" }
        return first.other_iata ?? first.altitude ?? "Airport schedule"
    }
}

private extension String? {
    var orEmpty: String { self ?? "" }
}
struct GameRow: View {
    let game: Game
    let leagueLabel: String?
    var isPinned: Bool = false

    // Drives the continuous animation for the music waveform
    @State private var waveformActive = false
    var activeSituation: String {
        guard let s = game.situation else { return "" }
        if let en = s.emptyNet, en { return "EMPTY NET" }
        if let pp = s.powerPlay, pp { return "PWR PLAY" }
        return ""
    }

    var situationColor: Color {
        if let s = game.situation {
            if s.isRedZone == true { return Color.red }
            if s.emptyNet == true { return Color.red }
        }
        return Color.yellow
    }

    func ownsActiveTeam(isHome: Bool) -> Bool {
        guard let s = game.situation else { return false }
        let activeTeam = (s.activeTeam ?? "").trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        let team = (isHome ? game.safeHomeAbbr : game.safeAwayAbbr).uppercased()
        return !activeTeam.isEmpty && activeTeam == team
    }

    var isFootball: Bool {
        ["nfl", "ncf_fbs", "ncf_fcs"].contains(game.sport)
    }

    var isBaseball: Bool { game.sport == "mlb" }

    var hasBaseballCount: Bool {
        guard let s = game.situation else { return false }
        return s.balls != nil && s.strikes != nil && s.outs != nil
    }

    func ownsFootballContext(isHome: Bool) -> Bool {
        guard isFootball, game.situation != nil else { return false }
        return ownsActiveTeam(isHome: isHome)
    }

    @ViewBuilder func teamLiveContext(isHome: Bool) -> some View {
        if ownsFootballContext(isHome: isHome), let s = game.situation {
            FootballDownContext(downDist: s.downDist, isRedZone: s.isRedZone == true)
        } else if isBaseball, hasBaseballCount, ownsActiveTeam(isHome: isHome), let s = game.situation,
                  let balls = s.balls, let strikes = s.strikes, let outs = s.outs {
            BaseballCountContext(balls: balls, strikes: strikes, outs: outs)
        } else if !activeSituation.isEmpty, ownsActiveTeam(isHome: isHome) {
            SituationPill(text: activeSituation, color: situationColor)
        }
    }

    var isSituationGlobal: Bool {
        guard game.situation != nil else { return false }
        if isFootball || isBaseball { return false }
        return !activeSituation.isEmpty && !ownsActiveTeam(isHome: true) && !ownsActiveTeam(isHome: false)
    }

    var formattedSport: String {
        if let label = leagueLabel { return label }
        switch game.sport {
        case "ncf_fbs": return "FBS"
        case "ncf_fcs": return "FCS"
        case "soccer_epl": return "EPL"
        case "soccer_champ": return "EFL"
        case "soccer_wc": return "FIFA"
        case "hockey_olympics": return "OLY"
        default: return game.sport.uppercased()
        }
    }

    var isLive: Bool { return game.state == "in" }
    var isSoccer: Bool { return game.sport.contains("soccer") }

    func prioritizeVibrantColor(primary: String?, alternate: String?) -> Color {
        let pColor = Color(hex: primary ?? "#000000")
        let aColor = Color(hex: alternate ?? "#000000")
        if pColor.isGrayscaleOrBlack && !aColor.isGrayscaleOrBlack { return aColor }
        return pColor
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)

        if game.type == "stock_ticker" {
            // MARK: - STOCK CARD
            HStack(spacing: 12) {
                Capsule().fill(Color.blue).frame(width: 4, height: 55)
                if let u = game.home_logo, !u.isEmpty {
                    TeamLogoView(url: u, abbr: game.safeHomeAbbr, size: 32)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(game.safeHomeAbbr).font(.headline).bold().foregroundColor(.white)
                    Text(game.tourney_name ?? "MARKET").font(.caption2).bold().foregroundColor(.gray)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    Text("$\(game.home_score)").font(.title3).bold().foregroundColor(.white)
                    HStack(spacing: 4) {
                        let changePct = game.away_score
                        let changeAmt = game.situation?.change ?? ""
                        let isUp = !changePct.contains("-")
                        Image(systemName: isUp ? "arrowtriangle.up.fill" : "arrowtriangle.down.fill").font(.system(size: 8))
                        Text("\(changeAmt) (\(changePct))").font(.caption).bold()
                    }
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(game.away_score.contains("-") ? Color.red.opacity(0.2) : Color.green.opacity(0.2))
                    .foregroundColor(game.away_score.contains("-") ? .red : .green)
                    .cornerRadius(6)
                }
            }
            .padding(12).background(Color(white: 0.15))
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)

        } else if game.type == "flight_visitor" {
            // MARK: - FLIGHT TRACKER CARD
            let isInAir = game.is_live == true
            let isDelayed = game.is_delayed == true || (game.delay_min ?? 0) >= 15
            let statusLower = game.status.lowercased()
            let isIdleStatus = ["pending", "no flight", "select flight", "waiting"].contains(statusLower)
            let progressPct = Double(game.progress ?? 0) / 100.0
            let planeColor: Color = isDelayed ? .red : (isInAir ? .orange : .gray)
            let statusBg: Color = isDelayed ? Color.red.opacity(0.2) : (isInAir ? Color.orange.opacity(0.2) : (isIdleStatus ? Color.gray.opacity(0.2) : Color.green.opacity(0.2)))
            let statusFg: Color = isDelayed ? .red : (isInAir ? .orange : (isIdleStatus ? .gray : .green))

            VStack(alignment: .leading, spacing: 10) {
                // Header
                HStack(spacing: 8) {
                    Image(systemName: "airplane.circle.fill")
                        .font(.title2)
                        .foregroundStyle(planeColor)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(game.guest_name ?? game.id)
                            .font(.headline).bold().foregroundColor(.white)
                        Text(game.route ?? "")
                            .font(.caption).foregroundColor(.gray)
                    }
                    Spacer()
                    Text(game.status)
                        .font(.system(size: 11, weight: .bold))
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(statusBg)
                        .foregroundColor(statusFg)
                        .cornerRadius(6)
                }

                // Route visualization
                HStack(spacing: 0) {
                    Text(game.origin_city ?? "?")
                        .font(.system(size: 11, weight: .bold)).foregroundColor(.white)
                    Spacer()
                    Text(game.dest_city ?? "?")
                        .font(.system(size: 11, weight: .bold)).foregroundColor(.white)
                }

                // Progress bar
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.white.opacity(0.1)).frame(height: 6)
                    GeometryReader { geo in
                        Capsule().fill(planeColor)
                            .frame(width: max(6, geo.size.width * progressPct), height: 6)
                    }.frame(height: 6)
                    // Airplane icon on progress
                    GeometryReader { geo in
                        Image(systemName: "airplane")
                            .font(.system(size: 12))
                            .foregroundColor(planeColor)
                            .rotationEffect(.degrees(0))
                            .offset(x: max(0, min(geo.size.width - 14, geo.size.width * progressPct - 7)), y: -10)
                    }.frame(height: 6)
                }

                // Stats row
                HStack(spacing: 16) {
                    if let alt = game.alt, alt > 0 {
                        HStack(spacing: 4) {
                            Image(systemName: "arrow.up").font(.system(size: 9))
                            Text("\(alt.formatted()) ft").font(.system(size: 11, weight: .medium))
                        }.foregroundStyle(.gray)
                    }
                    if let spd = game.speed, spd > 0 {
                        HStack(spacing: 4) {
                            Image(systemName: "speedometer").font(.system(size: 9))
                            Text("\(spd) mph").font(.system(size: 11, weight: .medium))
                        }.foregroundStyle(.gray)
                    }
                    if let dist = game.dist, dist > 0 {
                        HStack(spacing: 4) {
                            Image(systemName: "location").font(.system(size: 9))
                            Text("\(dist) mi").font(.system(size: 11, weight: .medium))
                        }.foregroundStyle(.gray)
                    }
                    Spacer()
                    if let eta = game.eta_str, !eta.isEmpty {
                        HStack(spacing: 4) {
                            Image(systemName: "clock").font(.system(size: 9))
                            Text("ETA \(eta)").font(.system(size: 11, weight: .bold))
                        }.foregroundStyle(.orange)
                    }
                }
            }
            .padding(14)
            .background(
                LinearGradient(gradient: Gradient(colors: [Color.orange.opacity(0.15), Color(white: 0.12)]), startPoint: .topLeading, endPoint: .bottomTrailing)
            )
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [Color.orange.opacity(0.4), Color.white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)

        } else if game.type == "flight_weather" || game.type == "flight_arrival" || game.type == "flight_departure" {
            // Handled by AirportBoardView in HomeView — skip individual rendering
            EmptyView()

        } else if game.type == "leaderboard" {
            // MARK: - LEADERBOARD CARD
            HStack(spacing: 12) {
                Capsule().fill(isPinned ? Color.yellow : (game.is_shown ? Color.green : Color.red)).frame(width: 4, height: 55)
                VStack(alignment: .leading) {
                    Text(game.tourney_name ?? "Event").font(.headline).bold().foregroundColor(.white)
                    Text(game.status).font(.caption).foregroundColor(.gray)
                }
                Spacer()
                Text(formattedSport).font(.system(size: 14, weight: .bold)).foregroundColor(.white).padding(6).background(Color.white.opacity(0.1)).cornerRadius(6)
            }
            .padding(12).background(Color(white: 0.15))
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)

        } else if game.type == "music" {
            // MARK: - MUSIC CARD
            let isPaused = game.status.lowercased().contains("paused") || game.status.isEmpty

            HStack(spacing: 12) {
                Capsule().fill(Color(hex: "#1DB954")).frame(width: 4, height: 60)

                AsyncImage(url: URL(string: game.safeHomeLogo)) { phase in
                    if let image = phase.image {
                        image.resizable().aspectRatio(contentMode: .fill)
                    } else {
                        ZStack {
                            Color(white: 0.2)
                            Image(systemName: "music.note").foregroundStyle(.gray)
                        }
                    }
                }
                .frame(width: 50, height: 50)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1), lineWidth: 1))

                VStack(alignment: .leading, spacing: 4) {
                    Text(game.safeAwayAbbr)
                        .font(.headline).bold().foregroundColor(.white)
                        .lineLimit(1)

                    HStack(spacing: 6) {
                        Image(systemName: "mic.fill").font(.caption2).foregroundColor(.gray)
                        Text(game.safeHomeAbbr)
                            .font(.subheadline).foregroundColor(.gray)
                            .lineLimit(1)
                    }
                }

                Spacer()

                VStack(alignment: .trailing, spacing: 8) {
                    HStack(alignment: .center, spacing: 3) {
                        ForEach(0..<5) { i in
                            Capsule()
                                .fill(Color(hex: "#1DB954"))
                                .frame(width: 3, height: (!isPaused && waveformActive) ? CGFloat.random(in: 12...24) : 4)
                                .animation(
                                    !isPaused
                                    ? .easeInOut(duration: CGFloat.random(in: 0.4...0.7)).repeatForever(autoreverses: true).delay(Double(i) * 0.05)
                                    : .default,
                                    value: waveformActive
                                )
                        }
                    }
                    .frame(height: 24)
                    .onAppear { waveformActive = true }

                    Text(game.status)
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundColor(.white.opacity(0.9))
                        .padding(.horizontal, 6).padding(.vertical, 4)
                        .background(Color(hex: "#1DB954").opacity(0.2))
                        .cornerRadius(6)
                }
            }
            .padding(12).background(Color(white: 0.15))
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)

        } else {
            // MARK: - STANDARD SPORTS/WEATHER/CLOCK
            let homeColor = prioritizeVibrantColor(primary: game.home_color, alternate: game.home_alt_color)
            let awayColor = prioritizeVibrantColor(primary: game.away_color, alternate: game.away_alt_color)
            let bg = LinearGradient(gradient: Gradient(colors: [awayColor.opacity(0.3), homeColor.opacity(0.3)]), startPoint: .leading, endPoint: .trailing)
            HStack(spacing: 12) {
                Capsule().fill(isPinned ? Color.yellow : (game.is_shown ? Color.green : Color.red)).frame(width: 4, height: 55)
                if game.sport == "weather" {
                    HStack {
                        Image(systemName: game.situation?.icon == "sun" ? "sun.max.fill" : "cloud.fill").font(.title).foregroundColor(.yellow)
                        VStack(alignment: .leading) {
                            Text(game.safeAwayAbbr).font(.headline).bold().foregroundColor(.white)
                            Text(game.status).font(.caption).foregroundColor(.gray)
                        }
                        Spacer()
                        Text(game.safeHomeAbbr).font(.system(size: 24, weight: .bold)).foregroundColor(.white)
                    }
                } else if game.sport == "clock" {
                    HStack {
                        Image(systemName: "clock.fill").font(.title).foregroundColor(.blue)
                        Text("Clock Mode Active").font(.headline).bold().foregroundColor(.white)
                        Spacer()
                    }
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            TeamLogoView(url: game.safeAwayLogo, abbr: game.safeAwayAbbr, size: 22)
                            Text(game.safeAwayAbbr).font(.headline).bold().foregroundColor(.white)
                            if let so = game.situation?.shootout, let awayRes = so.away {
                                ShootoutBubbles(results: awayRes, maxDots: isSoccer ? 5 : 3)
                                    .padding(.horizontal, 4).padding(.vertical, 2)
                                    .background(Color.black.opacity(0.3)).cornerRadius(4)
                            }
                            else { teamLiveContext(isHome: false) }
                            Spacer(); Text(game.away_score).font(.headline).bold().foregroundColor(.white)
                        }
                        HStack {
                            TeamLogoView(url: game.safeHomeLogo, abbr: game.safeHomeAbbr, size: 22)
                            Text(game.safeHomeAbbr).font(.headline).bold().foregroundColor(.white)
                            if let so = game.situation?.shootout, let homeRes = so.home {
                                ShootoutBubbles(results: homeRes, maxDots: isSoccer ? 5 : 3)
                                    .padding(.horizontal, 4).padding(.vertical, 2)
                                    .background(Color.black.opacity(0.3)).cornerRadius(4)
                            }
                            else { teamLiveContext(isHome: true) }
                            Spacer(); Text(game.home_score).font(.headline).bold().foregroundColor(.white)
                        }
                    }
                    VStack(alignment: .trailing, spacing: 4) {
                        Text(game.status)
                            .font(.caption).bold().padding(.horizontal, 8).padding(.vertical, 4)
                            .background(isLive ? Color.red.opacity(0.1) : Color.white.opacity(0.1))
                            .cornerRadius(6).foregroundColor(.white)
                        Text(formattedSport).font(.caption2).foregroundStyle(.gray).multilineTextAlignment(.trailing)
                        if isSituationGlobal { SituationPill(text: activeSituation, color: situationColor) }
                    }.frame(width: 80, alignment: .trailing)
                }
            }
            .padding(12).background(bg)
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)
        }
    }
}
// ==========================================
// MARK: - AIRPORT BOARD VIEW
// ==========================================
