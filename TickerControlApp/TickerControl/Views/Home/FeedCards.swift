import Foundation
import SwiftUI

struct NowPlayingCard: View {
    let track: NowPlaying

    var body: some View {
        HStack(spacing: 14) {
            AsyncImage(url: URL(string: track.cover ?? "")) { phase in
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
                    Image(systemName: track.isPlaying ? "waveform" : "pause.fill")
                        .font(.caption).foregroundStyle(track.isPlaying ? .green : .secondary)
                    Text(track.isPlaying ? "NOW PLAYING" : "SPOTIFY")
                        .font(.caption2.weight(.bold)).foregroundStyle(track.isPlaying ? .green : .secondary)
                }
                Text(track.title ?? "No active Spotify playback").font(.headline).foregroundStyle(.white).lineLimit(1)
                Text(track.artist ?? "Choose an account in Music settings").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                ProgressView(value: track.fraction).tint(.green).opacity(track.duration == nil ? 0 : 1)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Color.white.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.green.opacity(track.isPlaying ? 0.55 : 0.2), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}

struct StockCard: View {
    let quote: StockQuote

    private var color: Color { quote.isUp ? .green : .red }

    var body: some View {
        HStack(spacing: 14) {
            AsyncImage(url: URL(string: quote.logo ?? "")) { phase in
                if let image = phase.image {
                    image.resizable().scaledToFit().padding(7)
                } else {
                    Text(quote.symbol.prefix(4)).font(.caption.weight(.heavy))
                }
            }
            .frame(width: 54, height: 54)
            .background(color.opacity(0.13))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))

            VStack(alignment: .leading, spacing: 5) {
                Text("MARKETS").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text(quote.symbol).font(.headline).foregroundStyle(.white)
                Text(quote.list.isEmpty ? "Live quote" : quote.list).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 5) {
                Text("$\(quote.price)").font(.headline.weight(.bold)).foregroundStyle(.white)
                Label("\(quote.changeAmount)  \(quote.changePercent)", systemImage: quote.isUp ? "arrow.up.right" : "arrow.down.right")
                    .font(.caption2.weight(.bold)).foregroundStyle(color)
            }
        }
        .feedCard(color)
    }
}

struct WeatherLocationCard: View {
    let report: WeatherReport

    var body: some View {
        HStack(spacing: 14) {
            CardIcon(symbol: weatherSymbol(report.condition), color: .blue, tint: .yellow, font: .system(size: 30))
            VStack(alignment: .leading, spacing: 5) {
                Text("LOCAL WEATHER").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text(report.city.isEmpty ? "Weather" : report.city).font(.headline).foregroundStyle(.white)
                Text(report.condition.capitalized).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Text("NOW").font(.caption2.weight(.bold)).foregroundStyle(.blue)
        }
        .feedCard(.blue)
    }
}

struct WeatherCurrentCard: View {
    let report: WeatherReport

    private var details: String {
        [report.wind.map { "Wind \($0) mph" }, report.humidity.map { "Humidity \($0)%" }].compactMap { $0 }.joined(separator: " · ")
    }

    var body: some View {
        HStack(spacing: 14) {
            CardIcon(symbol: "thermometer.medium", color: .orange)
            VStack(alignment: .leading, spacing: 5) {
                Text("CURRENT TEMPERATURE").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text("Feels like \(report.feels ?? report.temperature)°").font(.headline).foregroundStyle(.white)
                Text(details).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Text("\(report.temperature)°").font(.system(size: 30, weight: .bold, design: .rounded)).foregroundStyle(.white)
        }
        .feedCard(.orange)
    }
}

struct WeatherTodayCard: View {
    let report: WeatherReport

    var body: some View {
        let today = report.forecast.first
        HStack(spacing: 14) {
            CardIcon(symbol: weatherSymbol(today?.icon ?? report.condition), color: .cyan)
            VStack(alignment: .leading, spacing: 5) {
                Text("\(today?.day?.uppercased() ?? "TODAY") FORECAST").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text("High \(today?.high ?? "—")°  ·  Low \(today?.low ?? "—")°").font(.headline).foregroundStyle(.white)
                Text(today?.precipitation.map { "\($0)% precipitation chance" } ?? "Forecast updating")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .feedCard(.cyan)
    }
}

struct TrackedFlightCard: View {
    let flight: TrackedFlight

    private var accent: Color { flight.delayed ? .red : (flight.isLive ? .orange : .secondary) }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 10) {
                Image(systemName: "airplane.circle.fill").font(.title2).foregroundStyle(accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(flight.guestName ?? flight.id).font(.headline).foregroundStyle(.white)
                    Text(flight.route ?? "Tracked flight").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Text(flight.status.uppercased()).font(.caption2.weight(.bold)).foregroundStyle(accent)
            }
            HStack {
                Text(flight.originCity ?? "—").font(.caption.weight(.bold)).foregroundStyle(.white)
                Spacer()
                Image(systemName: "airplane").font(.caption).foregroundStyle(accent)
                Spacer()
                Text(flight.destinationCity ?? "—").font(.caption.weight(.bold)).foregroundStyle(.white)
            }
            ProgressView(value: min(max(Double(flight.progress ?? 0) / 100, 0), 1))
                .tint(accent).opacity(flight.progress == nil ? 0 : 1)
            if let eta = flight.eta, !eta.isEmpty {
                Text("ETA \(eta)").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .feedCard(accent)
    }
}

struct AirportCard: View {
    let board: AirportBoard

    var body: some View {
        HStack(spacing: 14) {
            CardIcon(symbol: "airplane.departure", color: .cyan, font: .title2)
            VStack(alignment: .leading, spacing: 4) {
                Text("AIRPORT ACTIVITY").font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                Text(board.code ?? "AIRPORT").font(.headline).foregroundStyle(.white)
                Text(board.city ?? "Live airport activity").font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            if let temperature = board.temperature, !temperature.isEmpty {
                VStack(alignment: .trailing, spacing: 4) {
                    Image(systemName: weatherSymbol(board.condition ?? "")).foregroundStyle(.cyan)
                    Text(temperature).font(.caption.weight(.bold)).foregroundStyle(.white)
                }
            }
        }
        .feedCard(.cyan)
    }
}

struct AirportScheduleCard: View {
    let title: String
    let symbol: String
    let flights: [AirportBoard.Flight]
    let color: Color

    var body: some View {
        HStack(spacing: 14) {
            CardIcon(symbol: symbol, color: color, font: .title2)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.caption2.weight(.bold)).foregroundStyle(color)
                Text(headline).font(.headline).foregroundStyle(.white).lineLimit(1)
                Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            Text("\(flights.count)").font(.title3.weight(.bold)).foregroundStyle(color)
        }
        .feedCard(color)
    }

    private var headline: String {
        guard let first = flights.first else { return "No scheduled flights" }
        let parts = [first.number, first.airport].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? "Scheduled flight" : parts.joined(separator: " ")
    }

    private var detail: String {
        guard let first = flights.first else { return "Waiting for schedule" }
        let parts = [first.city, first.status].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? "Airport schedule" : parts.joined(separator: " · ")
    }
}
