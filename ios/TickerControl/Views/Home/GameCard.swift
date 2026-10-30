import Foundation
import SwiftUI

/// A game of the feed: both teams with their scores, the live situation, and the status.
/// The left bar is yellow for the pinned game, green for a shown game, and red for a hidden game.
struct GameCard: View {
    let item: FeedItem
    let leagueLabel: String?
    let isPinned: Bool

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)
        HStack(spacing: 12) {
            Capsule().fill(isPinned ? Color.yellow : (item.isShown ? Color.green : Color.red)).frame(width: 4, height: 55)
            if let game = item.game {
                GameScore(game: game, leagueLabel: leagueLabel)
            } else {
                Image(systemName: "clock.fill").font(.title).foregroundColor(.blue)
                Text("Clock Mode Active").font(.headline).bold().foregroundColor(.white)
                Spacer()
            }
        }
        .padding(12)
        .background(background)
        .overlay(shape.strokeBorder(GlassEdge.gradient, lineWidth: 1))
        .clipShape(shape).shadow(color: .black.opacity(0.15), radius: 10, x: 0, y: 5)
    }

    private var background: some View {
        let colors = item.game.map { [Color.team($0.away).opacity(0.3), Color.team($0.home).opacity(0.3)] } ?? [Color(white: 0.15), Color(white: 0.15)]
        return LinearGradient(colors: colors, startPoint: .leading, endPoint: .trailing)
    }
}

private struct GameScore: View {
    let game: Game
    let leagueLabel: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            team(isHome: false)
            team(isHome: true)
        }
        VStack(alignment: .trailing, spacing: 4) {
            Text(game.status)
                .font(.caption).bold().padding(.horizontal, 8).padding(.vertical, 4)
                .background(game.state == "in" ? Color.red.opacity(0.1) : Color.white.opacity(0.1))
                .cornerRadius(6).foregroundColor(.white)
            Text(sportLabel).font(.caption2).foregroundStyle(.gray).multilineTextAlignment(.trailing)
            if let pill = sharedPill { SituationPill(text: pill.text, color: pill.color) }
        }
        .frame(width: 80, alignment: .trailing)
    }

    private func team(isHome: Bool) -> some View {
        let side = game.side(isHome: isHome)
        return HStack {
            TeamLogo(url: side.logo, abbr: side.abbr, size: 22)
            Text(side.abbr).font(.headline).bold().foregroundColor(.white)
            if let results = isHome ? game.situation?.shootout?.home : game.situation?.shootout?.away {
                ShootoutDots(results: results, slots: game.sport.contains("soccer") ? 5 : 3)
                    .padding(.horizontal, 4).padding(.vertical, 2)
                    .background(Color.black.opacity(0.3)).cornerRadius(4)
            } else {
                teamContext(isHome: isHome)
            }
            Spacer()
            Text(side.score).font(.headline).bold().foregroundColor(.white)
        }
    }

    // Live situation

    private var isFootball: Bool { ["nfl", "ncf_fbs", "ncf_fcs"].contains(game.sport) }
    private var isBaseball: Bool { game.sport == "mlb" }

    private func hasPossession(isHome: Bool) -> Bool {
        let active = (game.situation?.activeTeam ?? "").trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        return !active.isEmpty && active == game.side(isHome: isHome).abbr.uppercased()
    }

    /// The power play or the empty net, in the color of its danger.
    private var pill: (text: String, color: Color)? {
        guard let situation = game.situation else { return nil }
        if situation.emptyNet { return ("EMPTY NET", .red) }
        if situation.powerPlay { return ("PWR PLAY", situation.isRedZone ? .red : .yellow) }
        return nil
    }

    /// A situation that belongs to neither team shows under the status.
    private var sharedPill: (text: String, color: Color)? {
        guard !isFootball, !isBaseball, !hasPossession(isHome: true), !hasPossession(isHome: false) else { return nil }
        return pill
    }

    @ViewBuilder private func teamContext(isHome: Bool) -> some View {
        if let situation = game.situation, hasPossession(isHome: isHome) {
            if isFootball {
                if let down = situation.downDistance, !down.isEmpty {
                    SituationPill(text: down, color: situation.isRedZone ? .red : .yellow)
                }
            } else if isBaseball {
                if let balls = situation.balls, let strikes = situation.strikes, let outs = situation.outs {
                    BaseballCount(balls: balls, strikes: strikes, outs: outs)
                }
            } else if let pill {
                SituationPill(text: pill.text, color: pill.color)
            }
        }
    }

    private var sportLabel: String {
        if let leagueLabel { return leagueLabel }
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
}

struct SituationPill: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text).font(.system(size: 10, weight: .black)).foregroundColor(color)
            .padding(.horizontal, 6).padding(.vertical, 3).background(color.opacity(0.2))
            .cornerRadius(4).overlay(RoundedRectangle(cornerRadius: 4).stroke(color.opacity(0.3), lineWidth: 1))
    }
}

private struct BaseballCount: View {
    let balls: Int
    let strikes: Int
    let outs: Int

    var body: some View {
        HStack(spacing: 3) {
            count("B", balls, .green)
            count("S", strikes, .yellow)
            count("O", outs, .red)
        }
        .padding(.horizontal, 6).padding(.vertical, 3)
        .background(Color.white.opacity(0.12))
        .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color.white.opacity(0.16), lineWidth: 1))
        .cornerRadius(4)
    }

    @ViewBuilder private func count(_ label: String, _ value: Int, _ color: Color) -> some View {
        Text(label).font(.system(size: 8, weight: .black)).foregroundStyle(color)
        Text("\(value)").font(.system(size: 10, weight: .black)).foregroundStyle(.white)
    }
}

/// The shootout attempts of one team: a green check for a goal, a red cross for a miss, and an open circle for a pending attempt.
private struct ShootoutDots: View {
    let results: [String]
    let slots: Int

    var body: some View {
        HStack(spacing: 2) {
            ForEach(0..<max(slots, results.count), id: \.self) { index in
                switch index < results.count ? results[index] : "" {
                case "goal":
                    Image(systemName: "checkmark.circle.fill").symbolRenderingMode(.palette).foregroundStyle(.white, .green)
                case "miss":
                    Image(systemName: "xmark.circle.fill").symbolRenderingMode(.palette).foregroundStyle(.white, .red)
                default:
                    Image(systemName: "circle").foregroundStyle(index < results.count ? Color.gray : Color.gray.opacity(0.5))
                }
            }
            .font(.system(size: 8))
        }
    }
}
