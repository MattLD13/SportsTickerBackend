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

struct FirstRunSetupView: View {
    @ObservedObject var vm: TickerViewModel
    @State private var showWiFiSetup = false
    @State private var showPairing = false

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(red: 0.08, green: 0.12, blue: 0.18), Color(red: 0.02, green: 0.03, blue: 0.05)],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 24) {
                    Spacer(minLength: 70)
                    Image(systemName: "rectangle.inset.filled.and.person.filled")
                        .font(.system(size: 42, weight: .medium))
                        .foregroundColor(.blue)
                    VStack(spacing: 8) {
                        Text("Set up your ticker")
                            .font(.system(size: 32, weight: .bold))
                            .foregroundColor(.white)
                        Text("Connect the ticker to Wi-Fi, then pair this app to control it.")
                            .multilineTextAlignment(.center)
                            .foregroundColor(.white.opacity(0.65))
                            .padding(.horizontal, 28)
                    }

                    VStack(spacing: 12) {
                        Button { showWiFiSetup = true } label: {
                            Label("Set Up Wi-Fi", systemImage: "wifi")
                                .frame(maxWidth: .infinity)
                                .padding()
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.blue)

                        Button { showPairing = true } label: {
                            Text("Connect an existing ticker with a pair code")
                                .font(.footnote.weight(.semibold))
                                .foregroundColor(.white.opacity(0.72))
                        }
                        .buttonStyle(.plain)
                    }
                    .padding(.horizontal, 28)

                    Text("Already connected to the same ticker? Ask its owner for a fresh pair code.")
                        .font(.caption)
                        .multilineTextAlignment(.center)
                        .foregroundColor(.white.opacity(0.45))
                        .padding(.horizontal, 38)
                    Spacer(minLength: 80)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .sheet(isPresented: $showWiFiSetup) {
            WiFiSetupView(vm: vm, isPresented: $showWiFiSetup)
        }
        .sheet(isPresented: $showPairing) {
            PairingView(vm: vm, isPresented: $showPairing)
        }
    }
}
