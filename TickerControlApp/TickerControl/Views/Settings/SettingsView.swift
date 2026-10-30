import Foundation
import SwiftUI

struct SettingsView: View {
    @Environment(TickerStore.self) private var store
    @State private var showPairing = false
    @State private var confirmingReboot = false

    var body: some View {
        @Bindable var store = store
        ScrollView {
            VStack(spacing: 24) {
                HStack { ScreenTitle(text: "Settings"); Spacer() }.padding(.horizontal).padding(.top, 80)

                VStack(alignment: .leading, spacing: 10) {
                    Text("CONNECTION").sectionHeader()
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Server URL").font(.caption).foregroundColor(.gray)
                        TextField("https://...", text: $store.serverURL)
                            .textFieldStyle(.plain).padding(10)
                            .background(Color.black.opacity(0.2)).cornerRadius(8)
                            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1)))
                            .foregroundColor(.white)
                            .keyboardType(.URL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .onSubmit { store.start() }
                    }.padding().liquidGlass()
                }.padding(.horizontal)

                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text("MY DEVICES").sectionHeader()
                        Spacer()
                        Button { showPairing = true } label: { Text("Pair New").font(.caption).bold().foregroundColor(.blue) }
                    }
                    if store.devices.isEmpty {
                        Text("No devices paired.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    } else {
                        ForEach(store.devices) { DeviceCard(device: $0) }
                    }
                }.padding(.horizontal)

                Button(action: reboot) {
                    Label(confirmingReboot ? "Tap Again to Confirm" : "Reboot Ticker",
                          systemImage: confirmingReboot ? "exclamationmark.triangle.fill" : "power")
                        .frame(maxWidth: .infinity).padding()
                        .background(confirmingReboot ? Color.orange.opacity(0.2) : Color.red.opacity(0.2))
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                        .foregroundColor(confirmingReboot ? .orange : .red)
                        .animation(.easeInOut, value: confirmingReboot)
                }
                .padding(.horizontal)

                Spacer(minLength: 120)
            }
        }
        .sheet(isPresented: $showPairing) { PairingView() }
        .alert("Pair Code", isPresented: Binding(
            get: { store.pairCodeMessage != nil }, set: { if !$0 { store.pairCodeMessage = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(store.pairCodeMessage ?? "")
        }
    }

    /// The first tap asks for confirmation for three seconds. The second tap reboots the ticker.
    private func reboot() {
        guard confirmingReboot else {
            confirmingReboot = true
            Task {
                try? await Task.sleep(for: .seconds(3))
                confirmingReboot = false
            }
            return
        }
        confirmingReboot = false
        Task { await store.reboot() }
    }
}
