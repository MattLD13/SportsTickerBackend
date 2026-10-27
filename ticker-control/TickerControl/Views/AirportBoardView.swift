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

struct AirportBoardView: View {
    let flights: [Game]

    private var weatherItem: Game? { flights.first(where: { $0.type == "flight_weather" }) }
    private var arrivals: [Game] { flights.filter { $0.type == "flight_arrival" } }
    private var departures: [Game] { flights.filter { $0.type == "flight_departure" } }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)

        VStack(spacing: 12) {
            // ====== CARD 1: AIRPORT INFO ======
            if let wx = weatherItem {
                VStack(spacing: 0) {
                    // Top: Airport name banner
                    HStack(spacing: 0) {
                        HStack(spacing: 10) {
                            ZStack {
                                Circle()
                                    .fill(
                                        RadialGradient(gradient: Gradient(colors: [Color.cyan.opacity(0.25), Color.cyan.opacity(0.05)]), center: .center, startRadius: 0, endRadius: 24)
                                    )
                                    .frame(width: 44, height: 44)
                                Image(systemName: "airplane")
                                    .font(.system(size: 20, weight: .semibold))
                                    .foregroundStyle(.cyan)
                                    .rotationEffect(.degrees(-45))
                            }

                            VStack(alignment: .leading, spacing: 2) {
                                Text(wx.safeHomeAbbr)
                                    .font(.system(size: 20, weight: .bold, design: .rounded))
                                    .foregroundColor(.white)
                                Text("LIVE ACTIVITY")
                                    .font(.system(size: 9, weight: .heavy, design: .rounded))
                                    .tracking(2)
                                    .foregroundStyle(.cyan.opacity(0.5))
                            }
                        }

                        Spacer()

                        // Weather block
                        HStack(spacing: 10) {
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(wx.status)
                                    .font(.system(size: 11, weight: .medium))
                                    .foregroundColor(.gray)
                                Text(wx.safeAwayAbbr)
                                    .font(.system(size: 26, weight: .bold, design: .rounded))
                                    .foregroundColor(.white)
                            }
                            Image(systemName: weatherIcon(for: wx.status))
                                .font(.system(size: 24))
                                .symbolRenderingMode(.hierarchical)
                                .foregroundStyle(.cyan)
                        }
                    }
                    .padding(16)
                }
                .background(
                    LinearGradient(gradient: Gradient(colors: [
                        Color.cyan.opacity(0.10),
                        Color(white: 0.07)
                    ]), startPoint: .topLeading, endPoint: .bottomTrailing)
                )
                .overlay(
                    shape.strokeBorder(
                        LinearGradient(gradient: Gradient(colors: [Color.cyan.opacity(0.4), Color.cyan.opacity(0.08)]),
                                       startPoint: .topLeading, endPoint: .bottomTrailing),
                        lineWidth: 1
                    )
                )
                .clipShape(shape)
                .shadow(color: Color.cyan.opacity(0.06), radius: 12, x: 0, y: 6)
            }

            // ====== CARD 2: ARRIVALS ======
            if !arrivals.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    // Header
                    HStack(spacing: 8) {
                        Image(systemName: "airplane.arrival")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.green)
                        Text("ARRIVALS")
                            .font(.system(size: 11, weight: .heavy, design: .rounded))
                            .tracking(1.5)
                            .foregroundStyle(.green.opacity(0.8))
                        Spacer()
                        Text("\(arrivals.count)")
                            .font(.system(size: 11, weight: .bold, design: .rounded))
                            .foregroundStyle(.green.opacity(0.5))
                    }
                    .padding(.horizontal, 16).padding(.top, 14).padding(.bottom, 10)

                    // Divider
                    Rectangle().fill(Color.green.opacity(0.1)).frame(height: 1)

                    // Flight rows
                    ForEach(Array(arrivals.enumerated()), id: \.element.id) { index, arr in
                        HStack(spacing: 12) {
                            // Flight number
                            Text(arr.safeAwayAbbr)
                                .font(.system(size: 14, weight: .bold, design: .monospaced))
                                .foregroundColor(.white)
                                .frame(width: 80, alignment: .leading)

                            // Route
                            HStack(spacing: 6) {
                                Text(arr.safeHomeAbbr)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundColor(.white.opacity(0.6))
                                Image(systemName: "arrow.right")
                                    .font(.system(size: 9, weight: .bold))
                                    .foregroundStyle(.green.opacity(0.4))
                                Image(systemName: "mappin.circle.fill")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.green.opacity(0.6))
                            }

                            Spacer()

                            // Status pill
                            let arrDelayed = arr.status.uppercased() == "DELAYED"
                            HStack(spacing: 4) {
                                Circle().fill(arrDelayed ? Color.orange : Color.green).frame(width: 4, height: 4)
                                Text(arrDelayed ? "DELAYED" : "INBOUND")
                                    .font(.system(size: 8, weight: .heavy, design: .rounded))
                            }
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background((arrDelayed ? Color.orange : Color.green).opacity(0.1))
                            .foregroundColor(arrDelayed ? .orange : .green)
                            .clipShape(Capsule())
                        }
                        .padding(.horizontal, 16).padding(.vertical, 10)

                        if index < arrivals.count - 1 {
                            Rectangle().fill(Color.white.opacity(0.04)).frame(height: 1).padding(.horizontal, 16)
                        }
                    }

                    Spacer().frame(height: 6)
                }
                .background(Color(white: 0.08))
                .overlay(shape.strokeBorder(Color.green.opacity(0.12), lineWidth: 1))
                .clipShape(shape)
                .shadow(color: Color.black.opacity(0.1), radius: 8, x: 0, y: 4)
            }

            // ====== CARD 3: DEPARTURES ======
            if !departures.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    // Header
                    HStack(spacing: 8) {
                        Image(systemName: "airplane.departure")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.blue)
                        Text("DEPARTURES")
                            .font(.system(size: 11, weight: .heavy, design: .rounded))
                            .tracking(1.5)
                            .foregroundStyle(.blue.opacity(0.8))
                        Spacer()
                        Text("\(departures.count)")
                            .font(.system(size: 11, weight: .bold, design: .rounded))
                            .foregroundStyle(.blue.opacity(0.5))
                    }
                    .padding(.horizontal, 16).padding(.top, 14).padding(.bottom, 10)

                    // Divider
                    Rectangle().fill(Color.blue.opacity(0.1)).frame(height: 1)

                    // Flight rows
                    ForEach(Array(departures.enumerated()), id: \.element.id) { index, dep in
                        HStack(spacing: 12) {
                            // Flight number
                            Text(dep.safeAwayAbbr)
                                .font(.system(size: 14, weight: .bold, design: .monospaced))
                                .foregroundColor(.white)
                                .frame(width: 80, alignment: .leading)

                            // Route
                            HStack(spacing: 6) {
                                Image(systemName: "mappin.circle.fill")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.blue.opacity(0.6))
                                Image(systemName: "arrow.right")
                                    .font(.system(size: 9, weight: .bold))
                                    .foregroundStyle(.blue.opacity(0.4))
                                Text(dep.safeHomeAbbr)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundColor(.white.opacity(0.6))
                            }

                            Spacer()

                            // Status pill
                            let depDelayed = dep.status.uppercased() == "DELAYED"
                            HStack(spacing: 4) {
                                Circle().fill(depDelayed ? Color.orange : Color.blue).frame(width: 4, height: 4)
                                Text(depDelayed ? "DELAYED" : "OUTBOUND")
                                    .font(.system(size: 8, weight: .heavy, design: .rounded))
                            }
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background((depDelayed ? Color.orange : Color.blue).opacity(0.1))
                            .foregroundColor(depDelayed ? .orange : .blue)
                            .clipShape(Capsule())
                        }
                        .padding(.horizontal, 16).padding(.vertical, 10)

                        if index < departures.count - 1 {
                            Rectangle().fill(Color.white.opacity(0.04)).frame(height: 1).padding(.horizontal, 16)
                        }
                    }

                    Spacer().frame(height: 6)
                }
                .background(Color(white: 0.08))
                .overlay(shape.strokeBorder(Color.blue.opacity(0.12), lineWidth: 1))
                .clipShape(shape)
                .shadow(color: Color.black.opacity(0.1), radius: 8, x: 0, y: 4)
            }
        }
    }
}
// ==========================================
// MARK: - 4. MAIN VIEW
// ==========================================
