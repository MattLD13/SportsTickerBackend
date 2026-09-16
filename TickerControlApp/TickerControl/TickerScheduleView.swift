import SwiftUI

struct TickerScheduleView: View {
    @ObservedObject var vm: TickerViewModel
    let device: TickerDevice
    @Binding var isPresented: Bool

    @State private var schedule: TickerScheduleResponse?
    @State private var selectedDate = Date()
    @State private var editingBlock: TickerScheduleBlock?
    @State private var editingCondition: TickerScheduleCondition?
    @State private var showingBlockEditor = false
    @State private var showingConditionEditor = false
    @State private var isLoading = false
    @State private var errorMessage: String?

    private var tickerTimeZone: TimeZone {
        TimeZone(identifier: schedule?.timezone ?? "") ?? .current
    }

    private var tickerCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = tickerTimeZone
        return calendar
    }

    private var selectedDay: Int {
        (tickerCalendar.component(.weekday, from: selectedDate) + 5) % 7
    }

    private var selectedBlocks: [TickerScheduleBlock] {
        schedule?.blocks.filter { $0.days_of_week.contains(selectedDay) } ?? []
    }

    private var supportedModes: [String] {
        let modes = device.profile?.capabilities.modes ?? [
            "sports", "stock", "weather", "music", "flights", "airports", "clock"
        ]
        return modes.isEmpty ? ["sports"] : modes
    }

    private var timezoneLabel: String {
        guard let value = schedule?.timezone, !value.isEmpty else { return "the ticker timezone" }
        return value
    }

    var body: some View {
        NavigationView {
            Form {
                Section {
                    DatePicker(
                        "Inspect recurring day",
                        selection: $selectedDate,
                        displayedComponents: [.date]
                    )
                    .datePickerStyle(.graphical)
                    Text("Rules repeat weekly in \(timezoneLabel).")
                        .font(.caption)
                        .foregroundColor(.secondary)
                } header: {
                    Text("Weekly schedule")
                }

                Section {
                    if selectedBlocks.isEmpty {
                        Text("No recurring block on this weekday.")
                            .foregroundColor(.secondary)
                    } else {
                        ForEach(selectedBlocks) { block in
                            ScheduleBlockRow(
                                block: block,
                                onEdit: {
                                    editingBlock = block
                                    showingBlockEditor = true
                                },
                                onDelete: { deleteBlock(block) }
                            )
                        }
                    }
                    Button {
                        editingBlock = nil
                        showingBlockEditor = true
                    } label: {
                        Label("Add recurring block", systemImage: "plus.circle.fill")
                    }
                } header: {
                    Text("\(selectedDate.formatted(.dateTime.weekday(.wide))) rules")
                }

                Section {
                    if let conditions = schedule?.conditions, !conditions.isEmpty {
                        ForEach(conditions) { condition in
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(condition.label)
                                    Text("Switches sports mode to Live Only")
                                        .font(.caption)
                                        .foregroundColor(.secondary)
                                }
                                Spacer()
                                Button("Edit") {
                                    editingCondition = condition
                                    showingConditionEditor = true
                                }
                                .buttonStyle(.borderless)
                            }
                        }
                    } else {
                        Text("No live-game condition is configured.")
                            .foregroundColor(.secondary)
                    }
                    if schedule?.conditions.isEmpty ?? true {
                        Button {
                            editingCondition = nil
                            showingConditionEditor = true
                        } label: {
                            Label("Add live-game condition", systemImage: "bolt.badge.clock")
                        }
                    }
                } header: {
                    Text("Conditions")
                } footer: {
                    Text("A condition applies only in sports mode, never overrides a pinned game, and returns to the scheduled view when live games fall below its threshold.")
                }

                Section {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(schedule?.effective.override == true ? "App override active" : "Follow schedule")
                            if let expiry = schedule?.effective.override_expires_at {
                                Text("Expires \(Date(timeIntervalSince1970: expiry).formatted(date: .abbreviated, time: .shortened))")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }
                        }
                        Spacer()
                        Button(schedule?.effective.override == true ? "Stop" : "Override") {
                            setOverride(!(schedule?.effective.override ?? false))
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.orange)
                    }
                } header: {
                    Text("Ticker override")
                } footer: {
                    Text("Selecting a mode in the app also starts an override. An override expires at the next schedule transition, then recurring rules resume.")
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .foregroundColor(.red)
                    }
                }
            }
            .environment(\.calendar, tickerCalendar)
            .navigationTitle("Schedule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    if isLoading { ProgressView() }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") { isPresented = false }
                }
            }
            .sheet(isPresented: $showingBlockEditor, onDismiss: loadSchedule) {
                ScheduleBlockEditor(
                    vm: vm,
                    tickerID: device.id,
                    block: editingBlock,
                    supportedModes: supportedModes,
                    timeZone: tickerTimeZone,
                    isPresented: $showingBlockEditor
                )
            }
            .sheet(isPresented: $showingConditionEditor, onDismiss: loadSchedule) {
                ScheduleConditionEditor(
                    vm: vm,
                    tickerID: device.id,
                    condition: editingCondition,
                    isPresented: $showingConditionEditor
                )
            }
            .onAppear(perform: loadSchedule)
        }
        .presentationDetents([.medium, .large])
    }

    private func loadSchedule() {
        isLoading = true
        vm.fetchSchedule(for: device.id) { result in
            isLoading = false
            switch result {
            case .success(let value):
                schedule = value
                errorMessage = nil
            case .failure(let error):
                errorMessage = error.localizedDescription
            }
        }
    }

    private func deleteBlock(_ block: TickerScheduleBlock) {
        vm.deleteScheduleBlock(tickerID: device.id, blockID: block.id) { result in
            switch result {
            case .success:
                loadSchedule()
            case .failure(let error):
                errorMessage = error.localizedDescription
            }
        }
    }

    private func setOverride(_ enabled: Bool) {
        vm.setScheduleOverride(tickerID: device.id, enabled: enabled) { result in
            switch result {
            case .success:
                loadSchedule()
                vm.fetchData()
            case .failure(let error):
                errorMessage = error.localizedDescription
            }
        }
    }
}

private struct ScheduleBlockRow: View {
    let block: TickerScheduleBlock
    let onEdit: () -> Void
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: block.mode == "sports" ? "sportscourt.fill" : "calendar.badge.clock")
                .foregroundColor(block.enabled ? .blue : .secondary)
            VStack(alignment: .leading, spacing: 3) {
                Text(block.timeLabel)
                    .font(.headline.monospacedDigit())
                Text([block.mode.capitalized, block.sports_filter?.replacingOccurrences(of: "_", with: " ").capitalized]
                    .compactMap { $0 }
                    .joined(separator: " • "))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            Spacer()
            Menu {
                Button("Edit", action: onEdit)
                Button("Delete", role: .destructive, action: onDelete)
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.title3)
            }
        }
        .opacity(block.enabled ? 1 : 0.5)
    }
}

private struct ScheduleBlockEditor: View {
    @ObservedObject var vm: TickerViewModel
    let tickerID: String
    let block: TickerScheduleBlock?
    let supportedModes: [String]
    let timeZone: TimeZone
    @Binding var isPresented: Bool

    @State private var selectedDays: Set<Int>
    @State private var startDate: Date
    @State private var endDate: Date
    @State private var endOfDay: Bool
    @State private var mode: String
    @State private var sportsFilter: String
    @State private var enabled: Bool
    @State private var errorMessage: String?
    @State private var isSaving = false

    private var calendar: Calendar {
        var value = Calendar(identifier: .gregorian)
        value.timeZone = timeZone
        return value
    }

    private let dayNames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    init(
        vm: TickerViewModel,
        tickerID: String,
        block: TickerScheduleBlock?,
        supportedModes: [String],
        timeZone: TimeZone,
        isPresented: Binding<Bool>
    ) {
        self.vm = vm
        self.tickerID = tickerID
        self.block = block
        self.supportedModes = supportedModes
        self.timeZone = timeZone
        _isPresented = isPresented
        var localCalendar = Calendar(identifier: .gregorian)
        localCalendar.timeZone = timeZone
        let currentDay = (localCalendar.component(.weekday, from: Date()) + 5) % 7
        _selectedDays = State(initialValue: Set(block?.days_of_week ?? [currentDay]))
        _startDate = State(initialValue: Self.date(minute: block?.start_minute ?? 480, timeZone: timeZone))
        _endDate = State(initialValue: Self.date(minute: min(block?.end_minute ?? 540, 1439), timeZone: timeZone))
        _endOfDay = State(initialValue: block?.end_minute == 1440)
        _mode = State(initialValue: block?.mode ?? supportedModes.first ?? "sports")
        _sportsFilter = State(initialValue: block?.sports_filter ?? "all")
        _enabled = State(initialValue: block?.enabled ?? true)
    }

    var body: some View {
        NavigationView {
            Form {
                Section("Repeats on") {
                    HStack {
                        Button("Weekdays") { selectedDays = Set(0...4) }
                        Button("Weekends") { selectedDays = Set(5...6) }
                        Button("Every day") { selectedDays = Set(0...6) }
                    }
                    .font(.caption)
                    ForEach(0..<dayNames.count, id: \.self) { day in
                        Toggle(dayNames[day], isOn: Binding(
                            get: { selectedDays.contains(day) },
                            set: { value in
                                if value { selectedDays.insert(day) }
                                else { selectedDays.remove(day) }
                            }
                        ))
                    }
                }

                Section("Time") {
                    DatePicker("Starts", selection: $startDate, displayedComponents: [.hourAndMinute])
                    Toggle("Runs through midnight", isOn: $endOfDay)
                    if !endOfDay {
                        DatePicker("Ends", selection: $endDate, displayedComponents: [.hourAndMinute])
                    }
                }

                Section("Mode") {
                    Picker("Mode", selection: $mode) {
                        ForEach(supportedModes, id: \.self) { value in
                            Text(value.capitalized).tag(value)
                        }
                    }
                    if mode == "sports" {
                        Picker("Sports view", selection: $sportsFilter) {
                            Text("All games").tag("all")
                            Text("Live only").tag("live")
                            Text("My teams").tag("my_teams")
                        }
                    }
                    Toggle("Enabled", isOn: $enabled)
                }

                if let errorMessage {
                    Text(errorMessage).foregroundColor(.red)
                }
            }
            .environment(\.calendar, calendar)
            .navigationTitle(block == nil ? "Add block" : "Edit block")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") { isPresented = false }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(isSaving ? "Saving…" : "Save") { save() }
                        .disabled(isSaving || selectedDays.isEmpty)
                }
            }
        }
    }

    private func save() {
        isSaving = true
        errorMessage = nil
        let start = minute(from: startDate)
        let end = endOfDay ? 1440 : minute(from: endDate)
        if !endOfDay && end <= start {
            isSaving = false
            errorMessage = "The end time must be after the start time."
            return
        }
        let completion: (Result<TickerScheduleBlock, Error>) -> Void = { result in
            isSaving = false
            switch result {
            case .success:
                isPresented = false
            case .failure(let error):
                errorMessage = error.localizedDescription
            }
        }
        if let block {
            vm.updateScheduleBlock(
                tickerID: tickerID,
                blockID: block.id,
                daysOfWeek: selectedDays.sorted(),
                startMinute: start,
                endMinute: end,
                mode: mode,
                sportsFilter: mode == "sports" ? sportsFilter : nil,
                enabled: enabled,
                completion: completion
            )
        } else {
            vm.createScheduleBlock(
                tickerID: tickerID,
                daysOfWeek: selectedDays.sorted(),
                startMinute: start,
                endMinute: end,
                mode: mode,
                sportsFilter: mode == "sports" ? sportsFilter : nil,
                enabled: enabled,
                completion: completion
            )
        }
    }

    private func minute(from date: Date) -> Int {
        calendar.component(.hour, from: date) * 60 + calendar.component(.minute, from: date)
    }

    private static func date(minute: Int, timeZone: TimeZone) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        let base = calendar.startOfDay(for: Date())
        return base.addingTimeInterval(TimeInterval(minute * 60))
    }
}

private struct ScheduleConditionEditor: View {
    @ObservedObject var vm: TickerViewModel
    let tickerID: String
    let condition: TickerScheduleCondition?
    @Binding var isPresented: Bool

    @State private var threshold: Int
    @State private var comparison: String
    @State private var enabled: Bool
    @State private var errorMessage: String?
    @State private var isSaving = false

    init(
        vm: TickerViewModel,
        tickerID: String,
        condition: TickerScheduleCondition?,
        isPresented: Binding<Bool>
    ) {
        self.vm = vm
        self.tickerID = tickerID
        self.condition = condition
        _isPresented = isPresented
        _threshold = State(initialValue: condition?.threshold ?? 5)
        _comparison = State(initialValue: condition?.`operator` ?? "gt")
        _enabled = State(initialValue: condition?.enabled ?? true)
    }

    var body: some View {
        NavigationView {
            Form {
                Section("Live sports condition") {
                    Picker("When live games", selection: $comparison) {
                        Text("More than").tag("gt")
                        Text("At least").tag("gte")
                    }
                    Stepper("\(threshold) games", value: $threshold, in: 1...30)
                    Toggle("Enabled", isOn: $enabled)
                    Label("Switch to Live Only while sports mode is active", systemImage: "sportscourt.fill")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Label("Pinned sports always wins", systemImage: "pin.fill")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                if let errorMessage {
                    Text(errorMessage).foregroundColor(.red)
                }
            }
            .navigationTitle(condition == nil ? "Add condition" : "Edit condition")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    HStack {
                        Button("Cancel") { isPresented = false }
                        if condition != nil {
                            Button("Delete", role: .destructive) { delete() }
                        }
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(isSaving ? "Saving…" : "Save") { save() }
                        .disabled(isSaving)
                }
            }
        }
    }

    private func save() {
        isSaving = true
        errorMessage = nil
        if let condition {
            vm.updateScheduleCondition(
                tickerID: tickerID,
                conditionID: condition.id,
                threshold: threshold,
                `operator`: comparison,
                enabled: enabled
            ) { result in
                finish(result)
            }
        } else {
            vm.createScheduleCondition(
                tickerID: tickerID,
                threshold: threshold,
                `operator`: comparison,
                enabled: enabled
            ) { result in
                finish(result)
            }
        }
    }

    private func finish(_ result: Result<TickerScheduleCondition, Error>) {
        isSaving = false
        switch result {
        case .success:
            isPresented = false
        case .failure(let error):
            errorMessage = error.localizedDescription
        }
    }

    private func delete() {
        guard let condition else { return }
        isSaving = true
        vm.deleteScheduleCondition(tickerID: tickerID, conditionID: condition.id) { result in
            isSaving = false
            switch result {
            case .success:
                isPresented = false
            case .failure(let error):
                errorMessage = error.localizedDescription
            }
        }
    }
}
