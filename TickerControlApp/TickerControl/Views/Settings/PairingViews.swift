import Foundation
import SwiftUI

struct PairingView: View {
    @Environment(TickerStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var shareGroup = false
    @State private var showWiFi = false
    @State private var pairing = false

    var body: some View {
        @Bindable var store = store
        NavigationStack {
            Form {
                Section("Instructions") {
                    Text("1. Ensure your Ticker is powered on.")
                    Text("2. Wait for the app pairing code. On Mini, look for APP PAIR.")
                    Text("3. Enter that code below. Use WIFI PIN only in Wi-Fi setup.")
                }
                Section("Device Info") {
                    TextField("Friendly Name", text: $store.pairName)
                    TextField("6-Digit App Code", text: $store.pairCode).keyboardType(.numberPad)
                    Toggle("Share teams and Spotify with my other tickers", isOn: $shareGroup)
                }
                Section("Ticker Wi-Fi") {
                    Text("Optional. Set up the ticker network before pairing this ticker.").font(.caption).foregroundColor(.secondary)
                    Button {
                        store.wifi.code = ""
                        showWiFi = true
                    } label: {
                        Label("Set Up Ticker Wi-Fi", systemImage: "wifi")
                    }
                }
                Button(pairing ? "Pairing..." : "Pair with Code") {
                    pairing = true
                    Task {
                        await store.pair(code: store.pairCode, name: store.pairName.isEmpty ? "My Ticker" : store.pairName, shareGroup: shareGroup)
                        pairing = false
                    }
                }
                .disabled(store.pairCode.count < 6 || pairing)
                if let error = store.pairError { Section { Text(error).foregroundColor(.red) } }
            }
            .navigationTitle("Pair Ticker")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Close") { dismiss() } } }
            .onAppear {
                shareGroup = store.canShareGroup
                store.pairError = nil
            }
            .sheet(isPresented: $showWiFi) { WiFiSetupView() }
            .alert("Success", isPresented: $store.pairSucceeded) {
                Button("OK") { dismiss() }
            } message: {
                Text("Ticker paired successfully!")
            }
        }
    }
}

struct WiFiSetupView: View {
    @Environment(TickerStore.self) private var store
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        @Bindable var store = store
        let busy = store.wifi.inProgress
        NavigationStack {
            Form {
                Section("Ticker Bluetooth") {
                    Text("Turn on Bluetooth and enter the temporary setup PIN shown after the ticker opens setup mode. The app sends Wi-Fi details through an encrypted local Bluetooth session, then pairs automatically when the ticker has a backend code.")
                    TextField("Six-digit setup PIN", text: $store.wifi.code)
                        .keyboardType(.numberPad).textContentType(.oneTimeCode).disabled(busy)
                }
                Section("Home Wi-Fi") {
                    Picker("Network", selection: $store.wifi.usesCurrentNetwork) {
                        Text("This iPhone's current Wi-Fi").tag(true)
                        Text("Different Wi-Fi network").tag(false)
                    }
                    if store.wifi.usesCurrentNetwork {
                        HStack {
                            Text(store.wifi.detectedSSID.isEmpty ? "Detecting network..." : store.wifi.detectedSSID)
                                .foregroundColor(store.wifi.detectedSSID.isEmpty ? .secondary : .primary)
                            Spacer()
                            Button("Refresh") { Task { await store.detectWiFi() } }.disabled(busy)
                        }
                    } else {
                        TextField("Network name", text: $store.wifi.ssid).textContentType(.username).disabled(busy)
                    }
                    SecureField("Wi-Fi password", text: $store.wifi.password).disabled(busy)
                    Button(busy ? "Connecting..." : "Connect ticker over Bluetooth") { Task { await store.startWiFiSetup() } }
                        .disabled(busy)
                }
                if !store.wifi.status.isEmpty { Section { Text(store.wifi.status).foregroundColor(.secondary) } }
                if let error = store.wifi.error { Section { Text(error).foregroundColor(.red) } }
            }
            .navigationTitle("Ticker Wi-Fi")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Close") { dismiss() } } }
            .onChange(of: store.wifi.usesCurrentNetwork) { _, current in store.wifi.ssid = current ? store.wifi.detectedSSID : "" }
            .task { await store.detectWiFi() }
            .onDisappear { store.cancelWiFiSetup() }
        }
    }
}

struct TickerSwitcherView: View {
    @Environment(TickerStore.self) private var store
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if store.devices.isEmpty {
                    Text("No paired tickers found.").foregroundColor(.secondary)
                } else {
                    ForEach(store.devices) { device in
                        let active = device.id == store.activeTickerID
                        Button {
                            store.switchTicker(device.id)
                            dismiss()
                        } label: {
                            HStack(spacing: 12) {
                                Image(systemName: active ? "checkmark.circle.fill" : "circle").foregroundColor(active ? .blue : .secondary)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(device.name).foregroundColor(.primary)
                                    Text(details(device)).font(.caption).foregroundColor(.secondary)
                                }
                                Spacer()
                                if let seen = device.lastSeen {
                                    Text(Date(timeIntervalSince1970: seen), style: .relative).font(.caption2).foregroundColor(.secondary)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Switch Ticker")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Close") { dismiss() } } }
        }
    }

    private func details(_ device: TickerRecord) -> String {
        let family = device.profile?.displayName.uppercased() ?? "TICKER"
        let size = device.profile.map { "\($0.display.width)×\($0.display.height)" } ?? ""
        return [family, size].filter { !$0.isEmpty }.joined(separator: " • ")
    }
}

/// The first screen of a new install: set up Wi-Fi on a new ticker, or pair with a code.
struct FirstRunSetupView: View {
    @State private var showWiFi = false
    @State private var showPairing = false

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.08, green: 0.12, blue: 0.18), Color(red: 0.02, green: 0.03, blue: 0.05)],
                           startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
            ScrollView {
                VStack(spacing: 24) {
                    Spacer(minLength: 70)
                    Image(systemName: "rectangle.inset.filled.and.person.filled").font(.system(size: 42, weight: .medium)).foregroundColor(.blue)
                    VStack(spacing: 8) {
                        Text("Set up your ticker").font(.system(size: 32, weight: .bold)).foregroundColor(.white)
                        Text("Connect the ticker to Wi-Fi, then pair this app to control it.")
                            .multilineTextAlignment(.center).foregroundColor(.white.opacity(0.65)).padding(.horizontal, 28)
                    }
                    VStack(spacing: 12) {
                        Button { showWiFi = true } label: {
                            Label("Set Up Wi-Fi", systemImage: "wifi").frame(maxWidth: .infinity).padding()
                        }
                        .buttonStyle(.borderedProminent).tint(.blue)
                        Button { showPairing = true } label: {
                            Text("Connect an existing ticker with a pair code").font(.footnote.weight(.semibold)).foregroundColor(.white.opacity(0.72))
                        }
                        .buttonStyle(.plain)
                    }
                    .padding(.horizontal, 28)
                    Text("Already connected to the same ticker? Ask its owner for a fresh pair code.")
                        .font(.caption).multilineTextAlignment(.center).foregroundColor(.white.opacity(0.45)).padding(.horizontal, 38)
                    Spacer(minLength: 80)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .sheet(isPresented: $showWiFi) { WiFiSetupView() }
        .sheet(isPresented: $showPairing) { PairingView() }
    }
}
