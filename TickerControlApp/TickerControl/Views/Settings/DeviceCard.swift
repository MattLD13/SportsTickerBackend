import Foundation
import SwiftUI
import UIKit

/// One paired ticker with its hardware settings: brightness, scroll speed, colors, and the stream delay.
struct DeviceCard: View {
    @Environment(TickerStore.self) private var store
    let device: TickerRecord

    @State private var brightness: Double
    @State private var speed: Double
    @State private var delay: Double
    @State private var showSchedule = false

    private let haptic = UIImpactFeedbackGenerator(style: .medium)

    init(device: TickerRecord) {
        self.device = device
        _brightness = State(initialValue: device.settings.brightness / 100)
        _speed = State(initialValue: Self.speedStep(device.settings.scrollSpeed))
        _delay = State(initialValue: device.settings.liveDelaySeconds)
    }

    /// The server stores the scroll speed as seconds per pixel step. The slider shows steps 1 (slow) to 10 (fast).
    static func speedStep(_ seconds: Double) -> Double { max(1, min(10, ((0.11 - seconds) * 100).rounded())) }
    static func scrollSeconds(_ step: Double) -> Double { 0.11 - step * 0.01 }

    private var isActive: Bool { device.id == store.activeTickerID }

    private var lastSeen: (text: String, online: Bool) {
        guard let seen = device.lastSeen else { return ("Never", false) }
        let age = Int(Date().timeIntervalSince1970 - seen)
        if age < 60 { return ("Online", true) }
        if age < 3600 { return ("Last seen: \(age / 60)m ago", false) }
        return ("Last seen: \(age / 3600)h ago", false)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            Divider().background(Color.white.opacity(0.1))
            sliders
            Divider().background(Color.white.opacity(0.1))
            HStack {
                Toggle("Inverted", isOn: Binding(get: { device.settings.inverted }, set: { change(DisplaySettingsPatch(inverted: $0)) }))
                    .labelsHidden().toggleStyle(SwitchToggleStyle(tint: .blue)).fixedSize()
                Text("Inverted").font(.caption)
                Spacer()
            }
            streamDelay
            Divider().background(Color.white.opacity(0.1))
            HStack {
                Button { UIPasteboard.general.string = device.id } label: { Label("Copy ID", systemImage: "doc.on.doc").font(.caption).bold() }
                Spacer()
                Button { Task { await store.showPairCode(for: device.id) } } label: { Label("Show Pair Code", systemImage: "number").font(.caption).bold() }
                Spacer()
                Button { Task { await store.unpair(device.id) } } label: {
                    Label("Unpair", systemImage: "trash").font(.caption).bold().foregroundColor(.red)
                }
            }
        }
        .padding().liquidGlass()
        .sheet(isPresented: $showSchedule) { ScheduleView(ticker: device) }
    }

    private var header: some View {
        HStack {
            Button { store.switchTicker(device.id) } label: {
                Image(systemName: isActive ? "checkmark.circle.fill" : "circle").font(.title3)
                    .foregroundColor(isActive ? .blue : .secondary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(isActive ? "Active ticker" : "Use this ticker")
            VStack(alignment: .leading) {
                Text(device.name).font(.headline).foregroundColor(.white)
                Text("ID: \(device.id.prefix(8))...").font(.caption).foregroundColor(.gray)
                if let profile = device.profile {
                    Text("\(profile.displayName.uppercased()) • \(profile.display.width)×\(profile.display.height)")
                        .font(.caption2).foregroundColor(.blue.opacity(0.8))
                }
            }
            Spacer()
            VStack(alignment: .trailing) {
                Image(systemName: "light.beacon.max.fill").foregroundColor(lastSeen.online ? .green : .red)
                Text(lastSeen.text).font(.system(size: 9)).foregroundColor(.gray)
            }
        }
    }

    @ViewBuilder private var sliders: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: "sun.max").font(.caption)
                Spacer()
                Text("\(Int(brightness * 100))%").font(.caption).monospacedDigit().bold()
            }
            Slider(value: $brightness, in: 0...1, step: 0.05, onEditingChanged: { editing in
                if !editing { change(DisplaySettingsPatch(brightness: (brightness * 100).rounded())) }
            })
            .tint(.white).onChange(of: brightness) { _, _ in haptic.impactOccurred() }
        }
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: "tortoise").font(.caption)
                Spacer()
                Text("Speed: \(Int(speed))").font(.caption).monospacedDigit().bold()
                Spacer()
                Image(systemName: "hare").font(.caption)
            }
            Slider(value: $speed, in: 1...10, step: 1, onEditingChanged: { editing in
                if !editing { change(DisplaySettingsPatch(scrollSpeed: Self.scrollSeconds(speed))) }
            })
            .tint(.blue).onChange(of: speed) { _, _ in haptic.impactOccurred() }
        }
    }

    private var streamDelay: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Toggle("Stream Delay", isOn: Binding(get: { device.settings.liveDelayMode }, set: { change(DisplaySettingsPatch(liveDelayMode: $0)) }))
                    .labelsHidden().toggleStyle(SwitchToggleStyle(tint: .orange))
                Text("Live Stream Delay").font(.caption)
                Spacer()
                Button { showSchedule = true } label: {
                    VStack(spacing: 2) {
                        Image(systemName: "calendar.badge.clock").font(.headline)
                        Text("Schedule").font(.caption2)
                    }
                    .foregroundColor(.yellow)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Edit schedule")
            }
            if device.settings.liveDelayMode {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Buffer: \(Int(delay))s").font(.caption).monospacedDigit().bold().foregroundColor(.orange)
                    Slider(value: $delay, in: 15...120, step: 15, onEditingChanged: { editing in
                        if !editing { change(DisplaySettingsPatch(liveDelaySeconds: delay)) }
                    })
                    .tint(.orange)
                }
                .transition(.opacity)
            }
        }
    }

    private func change(_ patch: DisplaySettingsPatch) {
        Task { await store.updateDevice(device.id, patch) }
    }
}
