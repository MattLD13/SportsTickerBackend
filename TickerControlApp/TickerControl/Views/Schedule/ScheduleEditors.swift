import Foundation
import SwiftUI
import UIKit

/// Add or change one schedule block.
struct ScheduleBlockEditor: View {
    @Environment(TickerStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let tickerID: String
    let block: ScheduleBlock?
    let modes: [String]
    let timeZone: TimeZone
    let onSaved: () -> Void

    @State private var days: Set<Int>
    @State private var startDate: Date
    @State private var endDate: Date
    @State private var mode: String
    @State private var sportsFilter: String
    @State private var enabled: Bool
    @State private var errorMessage: String?
    @State private var saving = false
    @State private var confirmingDelete = false

    init(tickerID: String, block: ScheduleBlock?, modes: [String], timeZone: TimeZone, days: [Int], start: Int, onSaved: @escaping () -> Void) {
        self.tickerID = tickerID
        self.block = block
        self.modes = modes
        self.timeZone = timeZone
        self.onSaved = onSaved
        _days = State(initialValue: Set(block?.daysOfWeek ?? days))
        _startDate = State(initialValue: SchedulePresentation.timeDate(minute: block?.startMinute ?? start, timeZone: timeZone))
        _endDate = State(initialValue: SchedulePresentation.timeDate(minute: block?.endMinute ?? min(start + 60, 1440), timeZone: timeZone))
        _mode = State(initialValue: block?.mode ?? modes.first ?? "sports")
        _sportsFilter = State(initialValue: block?.sportsFilter ?? "all")
        _enabled = State(initialValue: block?.enabled ?? true)
    }

    private var start: Int { SchedulePresentation.minute(startDate, timeZone: timeZone) }
    private var end: Int { SchedulePresentation.minute(endDate, timeZone: timeZone, endOfDay: true) }
    private var validRange: Bool { SchedulePresentation.validTimeRange(start: start, end: end) }
    private var valid: Bool { validRange && !days.isEmpty && modes.contains(mode) }

    var body: some View {
        NavigationStack {
            Form {
                modeSection
                repeatSection
                timeSection
                Section {
                    Toggle("Schedule enabled", isOn: $enabled).accessibilityIdentifier("schedule-editor-enabled")
                }
                if block != nil {
                    Section {
                        Button("Delete schedule", role: .destructive) { confirmingDelete = true }
                            .disabled(saving).accessibilityIdentifier("schedule-editor-delete")
                    }
                }
                if let errorMessage {
                    Section { Text(errorMessage).foregroundStyle(.red).accessibilityIdentifier("schedule-editor-error") }
                }
            }
            .navigationTitle(block == nil ? "Add schedule" : "Edit schedule")
            .navigationBarTitleDisplayMode(.inline)
            .environment(\.timeZone, timeZone)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.disabled(saving).accessibilityIdentifier("schedule-editor-cancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? "Saving…" : "Save") { run { try await store.saveBlock(tickerID, id: block?.id, draft) } }
                        .fontWeight(.semibold).disabled(saving || !valid).accessibilityIdentifier("schedule-editor-save")
                }
            }
            .interactiveDismissDisabled(saving)
            .alert("Delete this schedule?", isPresented: $confirmingDelete) {
                Button("Cancel", role: .cancel) {}
                Button("Delete schedule", role: .destructive) {
                    guard let block else { return }
                    run { try await store.deleteBlock(tickerID, id: block.id) }
                }
            } message: {
                if let block { Text("\(SchedulePresentation.modeName(block.mode)) · \(block.dayLabel) · \(block.timeLabel)") }
            }
        }
    }

    private var draft: ScheduleBlockDraft {
        ScheduleBlockDraft(daysOfWeek: days.sorted(), startMinute: start, endMinute: end, mode: mode,
                           sportsFilter: mode == "sports" ? sportsFilter : nil, enabled: enabled)
    }

    private func run(_ request: @escaping () async throws -> Void) {
        saving = true
        errorMessage = nil
        Task {
            do {
                try await request()
                onSaved()
                dismiss()
            } catch {
                errorMessage = error.localizedDescription
            }
            saving = false
        }
    }

    private var modeSection: some View {
        Section {
            Picker("Show", selection: $mode) {
                ForEach(modes, id: \.self) { Label(SchedulePresentation.modeName($0), systemImage: SchedulePresentation.modeSymbol($0)).tag($0) }
            }
            .pickerStyle(.navigationLink).accessibilityIdentifier("schedule-editor-mode")
            if mode == "sports" {
                Picker("Games", selection: $sportsFilter) {
                    Text("All games").tag("all")
                    Text("Live only").tag("live")
                    Text("My teams").tag("my_teams")
                }
                .pickerStyle(.segmented).accessibilityIdentifier("schedule-editor-sports-filter")
            }
        } header: { Text("What to show") }
    }

    private var repeatSection: some View {
        Section {
            HStack(spacing: 8) {
                preset("Every day", Array(0...6), id: "every-day")
                preset("Weekdays", Array(0...4), id: "weekdays")
                preset("Weekends", [5, 6], id: "weekends")
            }
            HStack(spacing: 4) {
                ForEach(0..<7, id: \.self) { day in
                    let selected = days.contains(day)
                    Button { if !days.insert(day).inserted { days.remove(day) } } label: {
                        Text(String(SchedulePresentation.weekdays[day].prefix(1)))
                            .font(.subheadline.weight(.semibold))
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(selected ? Color.blue : Color.gray.opacity(0.13), in: RoundedRectangle(cornerRadius: 10))
                            .foregroundStyle(selected ? Color.white : Color.secondary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(SchedulePresentation.weekdays[day])
                    .accessibilityValue(selected ? "Selected" : "Not selected")
                    .accessibilityIdentifier("schedule-day-\(day)")
                }
            }
        } header: {
            Text("Repeat")
        } footer: {
            Text(SchedulePresentation.repeatLabel(Array(days)))
                .foregroundStyle(days.isEmpty ? Color.red : Color.secondary)
                .accessibilityIdentifier("schedule-repeat-summary")
        }
    }

    private func preset(_ title: String, _ preset: [Int], id: String) -> some View {
        Button(title) { days = Set(preset) }
            .font(.caption.weight(.semibold))
            .buttonStyle(.bordered).buttonBorderShape(.capsule)
            .tint(days == Set(preset) ? .blue : .gray)
            .frame(maxWidth: .infinity, minHeight: 44)
            .accessibilityIdentifier("schedule-preset-\(id)")
    }

    private var timeSection: some View {
        Section {
            HStack {
                Text("Starts")
                Spacer()
                TimePicker(date: $startDate, timeZone: timeZone).frame(width: 140, height: 36).accessibilityIdentifier("schedule-start-time")
            }
            HStack {
                Text("Ends")
                Spacer()
                TimePicker(date: $endDate, timeZone: timeZone).frame(width: 140, height: 36).accessibilityIdentifier("schedule-end-time")
            }
        } header: {
            Text("When")
        } footer: {
            if validRange {
                Text("\(SchedulePresentation.clock(start)) – \(SchedulePresentation.clock(end)). Times use the ticker's time zone.")
                    .accessibilityIdentifier("schedule-time-summary")
            } else {
                Text("Choose an end time after the start. Select midnight to finish at the end of the day.")
                    .foregroundStyle(.red).accessibilityIdentifier("schedule-time-error")
            }
        }
    }
}

/// A compact time picker with 15-minute steps in the time zone of the ticker.
private struct TimePicker: UIViewRepresentable {
    @Binding var date: Date
    let timeZone: TimeZone

    func makeCoordinator() -> Coordinator { Coordinator(date: $date) }

    func makeUIView(context: Context) -> UIDatePicker {
        let picker = UIDatePicker()
        picker.datePickerMode = .time
        picker.preferredDatePickerStyle = .compact
        picker.minuteInterval = 15
        picker.addTarget(context.coordinator, action: #selector(Coordinator.changed(_:)), for: .valueChanged)
        return picker
    }

    func updateUIView(_ picker: UIDatePicker, context: Context) {
        context.coordinator.date = $date
        picker.timeZone = timeZone
        if picker.date != date { picker.setDate(date, animated: false) }
    }

    final class Coordinator: NSObject {
        var date: Binding<Date>
        init(date: Binding<Date>) { self.date = date }
        @objc func changed(_ picker: UIDatePicker) { date.wrappedValue = picker.date }
    }
}

/// Add or change the live sports rule.
struct ScheduleConditionEditor: View {
    @Environment(TickerStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let tickerID: String
    let condition: ScheduleCondition?
    let liveGames: Int
    let onSaved: () -> Void

    @State private var threshold: Int
    @State private var comparison: String
    @State private var enabled: Bool
    @State private var errorMessage: String?
    @State private var saving = false
    @State private var confirmingDelete = false

    init(tickerID: String, condition: ScheduleCondition?, liveGames: Int, onSaved: @escaping () -> Void) {
        self.tickerID = tickerID
        self.condition = condition
        self.liveGames = liveGames
        self.onSaved = onSaved
        _threshold = State(initialValue: condition?.threshold ?? 5)
        _comparison = State(initialValue: condition?.comparison ?? "gt")
        _enabled = State(initialValue: condition?.enabled ?? true)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("Show only live games", systemImage: "sportscourt.fill").font(.headline)
                    Text("Your ticker switches its sports feed when enough games are live.").font(.subheadline).foregroundStyle(.secondary)
                    Text("\(liveGames) live \(liveGames == 1 ? "game" : "games") on this ticker")
                        .font(.subheadline).foregroundStyle(.secondary).accessibilityIdentifier("schedule-live-count")
                }
                Section("When games are live") {
                    Picker("Number of games", selection: $comparison) {
                        Text("At least").tag("gte")
                        Text("More than").tag("gt")
                    }
                    .pickerStyle(.segmented).accessibilityIdentifier("schedule-condition-comparison")
                    Stepper("\(threshold) games", value: $threshold, in: 1...30).accessibilityIdentifier("schedule-condition-threshold")
                    Toggle("Rule enabled", isOn: $enabled)
                }
                Section {
                    Label("Runs while Sports mode is active", systemImage: "checkmark.circle")
                    Label("Pinned games keep priority", systemImage: "pin.fill")
                }
                .font(.subheadline).foregroundStyle(.secondary)
                if condition != nil {
                    Section { Button("Delete rule", role: .destructive) { confirmingDelete = true }.disabled(saving) }
                }
                if let errorMessage { Section { Text(errorMessage).foregroundStyle(.red) } }
            }
            .navigationTitle("Live sports rule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(saving) }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? "Saving…" : "Save") {
                        let draft = ScheduleConditionDraft(isNew: condition == nil, threshold: threshold, comparison: comparison, enabled: enabled)
                        run { try await store.saveCondition(tickerID, id: condition?.id, draft) }
                    }
                    .disabled(saving).accessibilityIdentifier("schedule-condition-save")
                }
            }
            .alert("Delete this live sports rule?", isPresented: $confirmingDelete) {
                Button("Cancel", role: .cancel) {}
                Button("Delete rule", role: .destructive) {
                    guard let condition else { return }
                    run { try await store.deleteCondition(tickerID, id: condition.id) }
                }
            }
            .interactiveDismissDisabled(saving)
        }
    }

    private func run(_ request: @escaping () async throws -> Void) {
        saving = true
        errorMessage = nil
        Task {
            do {
                try await request()
                onSaved()
                dismiss()
            } catch {
                errorMessage = error.localizedDescription
            }
            saving = false
        }
    }
}
