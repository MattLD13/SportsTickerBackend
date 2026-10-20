import SwiftUI

struct TickerScheduleView: View {
    @ObservedObject var vm: TickerViewModel
    let device: TickerDevice
    @Binding var isPresented: Bool

    @State private var schedule: TickerScheduleResponse?
    @State private var selectedDay = 0
    @State private var blockEditor: ScheduleBlockSelection?
    @State private var conditionEditor: ScheduleConditionSelection?
    @State private var blockToDelete: TickerScheduleBlock?
    @State private var pending: Set<String> = []
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var loadRevision = 0

    @ScaledMetric(relativeTo: .body) private var hourHeight: CGFloat = 72
    private var tickerTimeZone: TimeZone { TimeZone(identifier: schedule?.timezone ?? "") ?? .current }
    private var supportedModes: [String] {
        if let modes = device.profile?.capabilities.modes, !modes.isEmpty { return modes }
        let modes = ["sports", "stock", "weather", "music", "flights", "airports", "clock"]
        return device.capabilities.isEmpty ? modes : modes.filter { device.capabilities.contains($0) }
    }
    private var visibleBlocks: [TickerScheduleBlock] {
        SchedulePresentation.blocks(schedule?.blocks ?? [], on: selectedDay)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                calendarHeader
                if schedule != nil {
                    calendarBody
                    calendarControls
                } else if isLoading {
                    Spacer()
                    ProgressView("Loading your schedule…")
                    Spacer()
                } else {
                    ContentUnavailableView {
                        Label("Schedule unavailable", systemImage: "calendar.badge.exclamationmark")
                    } description: {
                        Text("Check the connection and try again.")
                    } actions: {
                        Button("Try again") { loadSchedule() }
                    }
                }
                if let errorMessage {
                    Text(errorMessage).font(.footnote).foregroundStyle(.red)
                        .padding(12).accessibilityIdentifier("schedule-error")
                }
            }
            .background(scheduleBackground)
            .navigationTitle("Schedule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { isPresented = false }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button { addSchedule() } label: { Image(systemName: "plus") }
                        .accessibilityLabel("Add schedule").accessibilityIdentifier("schedule-add")
                        .disabled(schedule == nil || isLoading)
                }
            }
            .sheet(item: $blockEditor) { selection in
                ScheduleBlockEditor(vm: vm, tickerID: device.id, block: selection.block,
                    supportedModes: supportedModes, timeZone: tickerTimeZone,
                    initialDays: [selection.day], initialStart: selection.start,
                    isPresented: Binding(get: { blockEditor != nil },
                        set: { if !$0 { blockEditor = nil } }), onSaved: scheduleChanged)
                    .id(selection.id)
            }
            .sheet(item: $conditionEditor) { selection in
                ScheduleConditionEditor(vm: vm, tickerID: device.id, condition: selection.condition,
                    isPresented: Binding(get: { conditionEditor != nil },
                        set: { if !$0 { conditionEditor = nil } }), onSaved: scheduleChanged)
                    .id(selection.id)
            }
            .alert("Delete this schedule?", isPresented: Binding(
                get: { blockToDelete != nil }, set: { if !$0 { blockToDelete = nil } }
            ), presenting: blockToDelete) { block in
                Button("Cancel", role: .cancel) {}
                Button("Delete schedule", role: .destructive) { deleteBlock(block) }
            } message: { block in
                Text("\(SchedulePresentation.modeName(block.mode)) · \(block.dayLabel) · \(block.timeLabel)")
            }
            .onAppear { loadSchedule() }
        }
        .preferredColorScheme(.dark)
        .tint(.blue)
        .presentationDetents([.large])
    }

    private var calendarHeader: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(device.name).font(.headline)
                    Text("Repeating week · \(schedule?.timezone.replacingOccurrences(of: "_", with: " ") ?? "Loading…")")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                if isLoading { ProgressView().controlSize(.small) }
            }
            if let effective = schedule?.effective, effective.override {
                Label("Paused until the next scheduled change", systemImage: "pause.circle")
                    .font(.caption).foregroundStyle(.orange)
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(0..<7, id: \.self) { day in
                        dayFilter(day)
                    }
                }
            }
            HStack {
                Text(SchedulePresentation.weekdays[selectedDay]).font(.title3.weight(.semibold))
                Spacer()
                if visibleBlocks.isEmpty, schedule != nil {
                    Button("Add schedule") { addSchedule() }
                        .font(.subheadline).accessibilityIdentifier("schedule-empty-add")
                } else {
                    Text("\(visibleBlocks.count) scheduled").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 14)
    }

    private func dayFilter(_ day: Int) -> some View {
        let selected = selectedDay == day
        return Button { selectedDay = day } label: {
            Text(String(SchedulePresentation.weekdays[day].prefix(3)))
                .font(.subheadline.weight(.semibold))
                .frame(minWidth: 44, minHeight: 44)
                .background(selected ? Color.blue : Color.white.opacity(0.06), in: Capsule())
                .foregroundStyle(selected ? Color.white : Color.secondary)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(SchedulePresentation.weekdays[day])
        .accessibilityValue(selected ? "Selected" : "Not selected")
        .accessibilityIdentifier("schedule-filter-\(day)")
    }

    private var calendarBody: some View {
        ScrollViewReader { proxy in
            ScrollView {
                calendarGrid
                Text("Tap a block to edit. Tap an empty hour to add a schedule.")
                    .font(.footnote).foregroundStyle(.secondary).padding(.horizontal, 20)
                Text("Outside these blocks, your ticker uses its usual settings.")
                    .font(.footnote).foregroundStyle(.secondary).padding(20)
            }
            .refreshable { await refreshSchedule() }
            .onAppear { proxy.scrollTo("schedule-hour-7", anchor: .top) }
            .onChange(of: selectedDay) { _, _ in
                proxy.scrollTo("schedule-hour-7", anchor: .top)
            }
        }
    }

    private var calendarGrid: some View {
        GeometryReader { geometry in
            ZStack(alignment: .topLeading) {
                VStack(spacing: 0) {
                    ForEach(0..<24, id: \.self) { hour in
                        hourRow(hour).id("schedule-hour-\(hour)")
                    }
                }
                ForEach(SchedulePresentation.calendarPlacements(visibleBlocks)) { placement in
                    calendarBlock(placement, width: geometry.size.width)
                }
            }
        }
        .frame(height: hourHeight * 24 + hourHeight)
        .padding(.trailing, 16)
    }

    private func hourRow(_ hour: Int) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(SchedulePresentation.hourLabel(hour)).font(.caption2).foregroundStyle(.secondary)
                .frame(width: 48, alignment: .trailing).offset(y: -7)
            VStack(spacing: 0) {
                Rectangle().fill(Color.white.opacity(0.12)).frame(height: 1)
                Spacer(minLength: 0)
                Rectangle().fill(Color.white.opacity(0.04)).frame(height: 1)
                Spacer(minLength: 0)
            }
            .contentShape(Rectangle())
            .onTapGesture { addSchedule(start: hour * 60) }
            .accessibilityElement()
            .accessibilityLabel("Add schedule at \(SchedulePresentation.clock(hour * 60))")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { addSchedule(start: hour * 60) }
            .accessibilityIdentifier("schedule-add-hour-\(hour)")
        }
        .frame(height: hourHeight)
    }

    private func calendarBlock(_ placement: ScheduleCalendarPlacement, width: CGFloat) -> some View {
        let block = placement.block
        let availableWidth = max(1, width - 62)
        let columnWidth = availableWidth / CGFloat(placement.columns)
        let height = CGFloat(placement.visualEnd - block.start_minute) / 60 * hourHeight
        return ScheduleCalendarBlock(block: block, pending: pending.contains(block.id)) { edit(block) }
            .frame(width: max(1, columnWidth - 4), height: max(1, height - 3), alignment: .topLeading)
            .offset(x: 56 + CGFloat(placement.column) * columnWidth,
                    y: CGFloat(block.start_minute) / 60 * hourHeight)
            .contextMenu {
                Button("Edit schedule", systemImage: "pencil") { edit(block) }
                Button(block.enabled ? "Turn off" : "Turn on", systemImage: "power") {
                    setEnabled(block, !block.enabled)
                }
                Button("Delete schedule", systemImage: "trash", role: .destructive) { blockToDelete = block }
            }
    }

    private var calendarControls: some View {
        HStack(spacing: 14) {
            Menu {
                ForEach(schedule?.conditions ?? []) { condition in
                    Button(condition.label) { conditionEditor = ScheduleConditionSelection(condition: condition) }
                        .accessibilityIdentifier("schedule-condition-\(condition.id)")
                }
                if schedule?.conditions.isEmpty ?? true {
                    Button("Add live sports rule") { conditionEditor = ScheduleConditionSelection(condition: nil) }
                        .accessibilityIdentifier("schedule-condition-add")
                }
            } label: {
                Label("Live sports", systemImage: "bolt.fill")
                    .font(.subheadline.weight(.medium)).frame(minHeight: 44)
            }
            .accessibilityIdentifier("schedule-rules")
            Spacer(minLength: 0)
            Button { setOverride(!(schedule?.effective.override ?? false)) } label: {
                Label(schedule?.effective.override == true ? "Resume schedule" : "Pause schedule",
                      systemImage: schedule?.effective.override == true ? "play.circle" : "pause.circle")
                    .font(.subheadline.weight(.medium)).frame(minHeight: 44)
            }
            .tint(.orange).disabled(pending.contains("override"))
            .accessibilityIdentifier("schedule-override")
        }
        .padding(.horizontal, 20).padding(.vertical, 5)
        .background(.ultraThinMaterial)
    }

    private var scheduleBackground: some View {
        LinearGradient(colors: [Color(red: 0.14, green: 0.19, blue: 0.25), Color(red: 0.04, green: 0.06, blue: 0.09)],
                       startPoint: .top, endPoint: .bottom).ignoresSafeArea()
    }

    private func addSchedule(start: Int = 480) {
        blockEditor = ScheduleBlockSelection(block: nil, day: selectedDay, start: start)
    }
    private func edit(_ block: TickerScheduleBlock) {
        blockEditor = ScheduleBlockSelection(block: block, day: selectedDay, start: block.start_minute)
    }
    private func scheduleChanged() { loadSchedule(); vm.fetchData() }

    private func loadSchedule(completion: @escaping () -> Void = {}) {
        loadRevision += 1
        let revision = loadRevision
        isLoading = true
        vm.fetchSchedule(for: device.id) { result in
            defer { completion() }
            guard loadRevision == revision else { return }
            isLoading = false
            switch result {
            case .success(let value):
                if schedule == nil, (0...6).contains(value.effective.day_of_week) {
                    selectedDay = value.effective.day_of_week
                }
                schedule = value
                errorMessage = nil
            case .failure(let error): errorMessage = error.localizedDescription
            }
        }
    }

    private func refreshSchedule() async {
        await withCheckedContinuation { continuation in
            loadSchedule { continuation.resume() }
        }
    }

    private func setEnabled(_ block: TickerScheduleBlock, _ enabled: Bool) {
        pending.insert(block.id)
        vm.updateScheduleBlock(tickerID: device.id, blockID: block.id,
            daysOfWeek: block.days_of_week, startMinute: block.start_minute, endMinute: block.end_minute,
            mode: block.mode, sportsFilter: block.sports_filter, enabled: enabled) { result in
                switch result {
                case .success: loadSchedule { pending.remove(block.id) }
                case .failure(let error): pending.remove(block.id); errorMessage = error.localizedDescription
                }
            }
    }

    private func deleteBlock(_ block: TickerScheduleBlock) {
        pending.insert(block.id)
        vm.deleteScheduleBlock(tickerID: device.id, blockID: block.id) { result in
            pending.remove(block.id)
            switch result {
            case .success: scheduleChanged()
            case .failure(let error): errorMessage = error.localizedDescription
            }
        }
    }

    private func setOverride(_ enabled: Bool) {
        pending.insert("override")
        vm.setScheduleOverride(tickerID: device.id, enabled: enabled) { result in
            pending.remove("override")
            switch result {
            case .success: scheduleChanged()
            case .failure(let error): errorMessage = error.localizedDescription
            }
        }
    }
}

private struct ScheduleBlockSelection: Identifiable {
    let id = UUID()
    let block: TickerScheduleBlock?
    let day: Int
    let start: Int
}

private struct ScheduleConditionSelection: Identifiable {
    let id = UUID()
    let condition: TickerScheduleCondition?
}

private struct ScheduleCalendarBlock: View {
    let block: TickerScheduleBlock
    let pending: Bool
    let edit: () -> Void

    private var color: Color {
        switch block.mode {
        case "sports": return .blue
        case "stock": return .green
        case "music": return .pink
        case "weather": return .cyan
        case "flights", "airports": return .orange
        default: return .purple
        }
    }

    var body: some View {
        Button(action: edit) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(SchedulePresentation.modeName(block.mode)).font(.subheadline.weight(.semibold))
                    if !block.enabled { Text("Off").font(.caption2).foregroundStyle(.secondary) }
                    Spacer(minLength: 0)
                    if pending { ProgressView().controlSize(.mini) }
                }
                Text(block.timeLabel).font(.caption).lineLimit(1).minimumScaleFactor(0.8)
                if block.mode == "sports", let filter = block.sports_filter, filter != "all" {
                    Text(filter == "live" ? "Live games only" : "My teams").font(.caption2)
                }
                Spacer(minLength: 0)
            }
            .foregroundStyle(.white).padding(.horizontal, 10).padding(.vertical, 6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(color.opacity(block.enabled ? 0.3 : 0.08), in: RoundedRectangle(cornerRadius: 8))
            .overlay(alignment: .leading) { RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 3) }
            .overlay {
                RoundedRectangle(cornerRadius: 8)
                    .strokeBorder(color.opacity(0.65), style: StrokeStyle(lineWidth: 1, dash: block.enabled ? [] : [4, 3]))
            }
            .contentShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain).disabled(pending).opacity(block.enabled ? 1 : 0.55)
        .accessibilityLabel("\(SchedulePresentation.modeName(block.mode)), \(block.timeLabel), \(block.dayLabel)")
        .accessibilityValue(block.enabled ? "Enabled" : "Disabled")
        .accessibilityIdentifier("schedule-edit-\(block.id)")
    }
}

private struct ScheduleBlockEditor: View {
    @ObservedObject var vm: TickerViewModel
    let tickerID: String
    let block: TickerScheduleBlock?
    let supportedModes: [String]
    let timeZone: TimeZone
    @Binding var isPresented: Bool
    let onSaved: () -> Void

    @State private var selectedDays: Set<Int>
    @State private var startDate: Date
    @State private var endDate: Date
    @State private var mode: String
    @State private var sportsFilter: String
    @State private var enabled: Bool
    @State private var errorMessage: String?
    @State private var isSaving = false

    private var start: Int { SchedulePresentation.minute(startDate, timeZone: timeZone) }
    private var end: Int { SchedulePresentation.minute(endDate, timeZone: timeZone, endOfDay: true) }
    private var validRange: Bool { SchedulePresentation.validTimeRange(start: start, end: end) }
    private var valid: Bool { validRange && !selectedDays.isEmpty && supportedModes.contains(mode) }

    init(vm: TickerViewModel, tickerID: String, block: TickerScheduleBlock?, supportedModes: [String],
         timeZone: TimeZone, initialDays: [Int]?, initialStart: Int,
         isPresented: Binding<Bool>, onSaved: @escaping () -> Void) {
        self.vm = vm
        self.tickerID = tickerID
        self.block = block
        self.supportedModes = supportedModes
        self.timeZone = timeZone
        self.onSaved = onSaved
        _isPresented = isPresented
        _selectedDays = State(initialValue: Set(block?.days_of_week ?? initialDays ?? Array(0...6)))
        _startDate = State(initialValue: SchedulePresentation.timeDate(minute: block?.start_minute ?? initialStart, timeZone: timeZone))
        _endDate = State(initialValue: SchedulePresentation.timeDate(minute: block?.end_minute ?? min(initialStart + 60, 1440), timeZone: timeZone))
        _mode = State(initialValue: block?.mode ?? supportedModes.first ?? "sports")
        _sportsFilter = State(initialValue: block?.sports_filter ?? "all")
        _enabled = State(initialValue: block?.enabled ?? true)
    }

    var body: some View {
        NavigationStack {
            Form {
                modeSection
                repeatSection
                timeSection
                Section {
                    Toggle("Schedule enabled", isOn: $enabled)
                        .accessibilityIdentifier("schedule-editor-enabled")
                }
                if let errorMessage {
                    Section {
                        Text(errorMessage).foregroundStyle(.red)
                            .accessibilityIdentifier("schedule-editor-error")
                    }
                }
            }
            .navigationTitle(block == nil ? "Add schedule" : "Edit schedule")
            .navigationBarTitleDisplayMode(.inline)
            .environment(\.timeZone, timeZone)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { isPresented = false }.disabled(isSaving)
                        .accessibilityIdentifier("schedule-editor-cancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Saving…" : "Save", action: save)
                        .fontWeight(.semibold).disabled(isSaving || !valid)
                        .accessibilityIdentifier("schedule-editor-save")
                }
            }
            .interactiveDismissDisabled(isSaving)
        }
    }

    private var modeSection: some View {
        Section {
            Picker("Show", selection: $mode) {
                ForEach(supportedModes, id: \.self) { item in
                    Label(SchedulePresentation.modeName(item), systemImage: modeSymbol(item)).tag(item)
                }
            }
            .pickerStyle(.navigationLink)
            .accessibilityIdentifier("schedule-editor-mode")
            if mode == "sports" {
                Picker("Games", selection: $sportsFilter) {
                    Text("All games").tag("all")
                    Text("Live only").tag("live")
                    Text("My teams").tag("my_teams")
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("schedule-editor-sports-filter")
            }
        } header: { Text("What to show") }
    }

    private var repeatSection: some View {
        Section {
            HStack(spacing: 8) {
                dayPreset("Every day", days: Array(0...6), id: "every-day")
                dayPreset("Weekdays", days: Array(0...4), id: "weekdays")
                dayPreset("Weekends", days: [5, 6], id: "weekends")
            }
            HStack(spacing: 4) {
                ForEach(0..<7, id: \.self) { day in
                    Button {
                        if !selectedDays.insert(day).inserted { selectedDays.remove(day) }
                    } label: {
                        Text(String(SchedulePresentation.weekdays[day].prefix(1)))
                            .font(.subheadline.weight(.semibold))
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(selectedDays.contains(day) ? Color.blue : Color.gray.opacity(0.13),
                                        in: RoundedRectangle(cornerRadius: 10))
                            .foregroundStyle(selectedDays.contains(day) ? .white : .secondary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(SchedulePresentation.weekdays[day])
                    .accessibilityValue(selectedDays.contains(day) ? "Selected" : "Not selected")
                    .accessibilityIdentifier("schedule-day-\(day)")
                }
            }
        } header: { Text("Repeat") } footer: {
            Text(SchedulePresentation.repeatLabel(Array(selectedDays)))
                .foregroundStyle(selectedDays.isEmpty ? .red : .secondary)
                .accessibilityIdentifier("schedule-repeat-summary")
        }
    }

    private func dayPreset(_ title: String, days: [Int], id: String) -> some View {
        Button(title) { selectedDays = Set(days) }
            .font(.caption.weight(.semibold))
            .buttonStyle(.bordered)
            .buttonBorderShape(.capsule)
            .tint(selectedDays == Set(days) ? .blue : .gray)
            .frame(maxWidth: .infinity, minHeight: 44)
            .accessibilityIdentifier("schedule-preset-\(id)")
    }

    private var timeSection: some View {
        Section {
            DatePicker("Starts", selection: $startDate, displayedComponents: .hourAndMinute)
                .datePickerStyle(.compact).accessibilityIdentifier("schedule-start-time")
            DatePicker("Ends", selection: $endDate, displayedComponents: .hourAndMinute)
                .datePickerStyle(.compact).accessibilityIdentifier("schedule-end-time")
        } header: { Text("When") } footer: {
            if validRange {
                Text("\(SchedulePresentation.clock(start)) – \(SchedulePresentation.clock(end)). Times use the ticker's time zone.")
                    .accessibilityIdentifier("schedule-time-summary")
            } else {
                Text("Choose an end time after the start. Select midnight to finish at the end of the day.")
                    .foregroundStyle(.red).accessibilityIdentifier("schedule-time-error")
            }
        }
    }

    private func modeSymbol(_ value: String) -> String {
        switch value {
        case "sports": return "sportscourt.fill"
        case "stock": return "chart.line.uptrend.xyaxis"
        case "music": return "music.note"
        case "weather": return "cloud.sun.fill"
        case "flights": return "airplane"
        case "airports": return "airplane.arrival"
        default: return "clock.fill"
        }
    }

    private func save() {
        guard valid else { return }
        isSaving = true
        errorMessage = nil
        let completion: (Result<TickerScheduleBlock, Error>) -> Void = { result in
            isSaving = false
            switch result {
            case .success: onSaved(); isPresented = false
            case .failure(let error): errorMessage = error.localizedDescription
            }
        }
        if let block {
            vm.updateScheduleBlock(tickerID: tickerID, blockID: block.id, daysOfWeek: selectedDays.sorted(),
                startMinute: start, endMinute: end, mode: mode,
                sportsFilter: mode == "sports" ? sportsFilter : nil, enabled: enabled, completion: completion)
        } else {
            vm.createScheduleBlock(tickerID: tickerID, daysOfWeek: selectedDays.sorted(), startMinute: start,
                endMinute: end, mode: mode, sportsFilter: mode == "sports" ? sportsFilter : nil,
                enabled: enabled, completion: completion)
        }
    }
}

private struct ScheduleConditionEditor: View {
    @ObservedObject var vm: TickerViewModel
    let tickerID: String
    let condition: TickerScheduleCondition?
    @Binding var isPresented: Bool
    let onSaved: () -> Void
    @State private var threshold: Int
    @State private var comparison: String
    @State private var enabled: Bool
    @State private var errorMessage: String?
    @State private var isSaving = false
    @State private var confirmingDelete = false

    init(vm: TickerViewModel, tickerID: String, condition: TickerScheduleCondition?,
         isPresented: Binding<Bool>, onSaved: @escaping () -> Void) {
        self.vm = vm; self.tickerID = tickerID; self.condition = condition; self.onSaved = onSaved
        _isPresented = isPresented
        _threshold = State(initialValue: condition?.threshold ?? 5)
        _comparison = State(initialValue: condition?.operator ?? "gte")
        _enabled = State(initialValue: condition?.enabled ?? true)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("Show only live games", systemImage: "sportscourt.fill").font(.headline)
                    Text("Your ticker switches its sports feed when enough games are live.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                Section("When games are live") {
                    Picker("Number of games", selection: $comparison) {
                        Text("At least").tag("gte")
                        Text("More than").tag("gt")
                    }.pickerStyle(.segmented)
                    Stepper("\(threshold) games", value: $threshold, in: 1...30)
                        .accessibilityIdentifier("schedule-condition-threshold")
                    Toggle("Rule enabled", isOn: $enabled)
                }
                Section {
                    Label("Runs while Sports mode is active", systemImage: "checkmark.circle")
                    Label("Pinned games keep priority", systemImage: "pin.fill")
                }.font(.subheadline).foregroundStyle(.secondary)
                if condition != nil {
                    Section {
                        Button("Delete rule", role: .destructive) { confirmingDelete = true }.disabled(isSaving)
                    }
                }
                if let errorMessage {
                    Section { Text(errorMessage).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Live sports rule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { isPresented = false }.disabled(isSaving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Saving…" : "Save", action: save).disabled(isSaving)
                        .accessibilityIdentifier("schedule-condition-save")
                }
            }
            .alert("Delete this live sports rule?", isPresented: $confirmingDelete) {
                Button("Cancel", role: .cancel) {}
                Button("Delete rule", role: .destructive, action: delete)
            }
            .interactiveDismissDisabled(isSaving)
        }
    }

    private func save() {
        isSaving = true; errorMessage = nil
        if let condition {
            vm.updateScheduleCondition(tickerID: tickerID, conditionID: condition.id, threshold: threshold,
                operator: comparison, enabled: enabled, completion: finish)
        } else {
            vm.createScheduleCondition(tickerID: tickerID, threshold: threshold,
                operator: comparison, enabled: enabled, completion: finish)
        }
    }

    private func finish(_ result: Result<TickerScheduleCondition, Error>) {
        isSaving = false
        switch result {
        case .success: onSaved(); isPresented = false
        case .failure(let error): errorMessage = error.localizedDescription
        }
    }

    private func delete() {
        guard let condition else { return }
        isSaving = true
        vm.deleteScheduleCondition(tickerID: tickerID, conditionID: condition.id) { result in
            isSaving = false
            switch result {
            case .success: onSaved(); isPresented = false
            case .failure(let error): errorMessage = error.localizedDescription
            }
        }
    }
}
