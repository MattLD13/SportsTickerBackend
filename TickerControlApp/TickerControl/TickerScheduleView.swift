import SwiftUI
import UIKit

struct TickerScheduleView: View {
    @ObservedObject var vm: TickerViewModel
    let device: TickerDevice
    @Binding var isPresented: Bool

    @State private var schedule: TickerScheduleResponse?
    @State private var scope: ScheduleCalendarScope = .weekdays
    @State private var selectedDay = 0
    @State private var dayCount = 3
    @State private var blockEditor: ScheduleBlockSelection?
    @State private var conditionEditor: ScheduleConditionSelection?
    @State private var updatingOverride = false
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var loadRevision = 0

    @ScaledMetric(relativeTo: .body) private var hourHeight: CGFloat = 72
    private var tickerTimeZone: TimeZone { TimeZone(identifier: schedule?.timezone ?? "") ?? .current }
    private var columns: [ScheduleCalendarColumn] { scope.columns(start: selectedDay, count: dayCount) }
    private var supportedModes: [String] {
        if let modes = device.profile?.capabilities.modes, !modes.isEmpty { return modes }
        let modes = ["sports", "stock", "weather", "music", "flights", "airports", "clock"]
        return device.capabilities.isEmpty ? modes : modes.filter { device.capabilities.contains($0) }
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
                ToolbarItem(placement: .cancellationAction) { Button("Done") { isPresented = false } }
                ToolbarItem(placement: .primaryAction) {
                    Button { addSchedule() } label: { Image(systemName: "plus") }
                        .accessibilityLabel("Add schedule").accessibilityIdentifier("schedule-add")
                        .disabled(schedule == nil || isLoading)
                }
            }
            .sheet(item: $blockEditor) { selection in
                ScheduleBlockEditor(vm: vm, tickerID: device.id, block: selection.block,
                    supportedModes: supportedModes, timeZone: tickerTimeZone,
                    initialDays: selection.days, initialStart: selection.start,
                    isPresented: Binding(get: { blockEditor != nil },
                        set: { if !$0 { blockEditor = nil } }), onSaved: scheduleChanged)
                    .id(selection.id)
            }
            .sheet(item: $conditionEditor) { selection in
                ScheduleConditionEditor(vm: vm, tickerID: device.id, condition: selection.condition,
                    liveGames: schedule?.live_games ?? 0,
                    isPresented: Binding(get: { conditionEditor != nil },
                        set: { if !$0 { conditionEditor = nil } }), onSaved: scheduleChanged)
                    .id(selection.id)
            }
            .onAppear { loadSchedule() }
        }
        .preferredColorScheme(.dark).tint(.blue).presentationDetents([.large])
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
            Picker("Schedule days", selection: $scope) {
                ForEach(ScheduleCalendarScope.allCases, id: \.self) { item in Text(item.rawValue).tag(item) }
            }.pickerStyle(.segmented).accessibilityIdentifier("schedule-scope-picker")
            if scope == .days { individualDayControls }
            HStack(spacing: 0) {
                Text(tickerTimeZone.abbreviation() ?? "Time").font(.caption2).foregroundStyle(.secondary).frame(width: 36)
                ForEach(columns) { column in
                    Text(columns.count == 1 ? column.title : String(column.title.prefix(3)))
                        .font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity)
                }
            }
        }
        .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 14)
    }

    private var individualDayControls: some View {
        VStack(spacing: 8) {
            HStack {
                Picker("Calendar view", selection: $dayCount) {
                    Text("Day").tag(1)
                    Text("3 days").tag(3)
                }.pickerStyle(.segmented).frame(width: 150).accessibilityIdentifier("schedule-view-picker")
                Spacer()
                Button { selectedDay = (selectedDay - dayCount + 7) % 7 } label: {
                    Image(systemName: "chevron.left").frame(width: 36, height: 44)
                }.accessibilityLabel("Previous days")
                Button { selectedDay = (selectedDay + dayCount) % 7 } label: {
                    Image(systemName: "chevron.right").frame(width: 36, height: 44)
                }.accessibilityLabel("Next days")
            }
            if dayCount == 1 {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) { ForEach(0..<7, id: \.self) { dayFilter($0) } }
                }
            }
        }
    }

    private func dayFilter(_ day: Int) -> some View {
        Button { selectedDay = day } label: {
            Text(String(SchedulePresentation.weekdays[day].prefix(3))).font(.subheadline.weight(.semibold))
                .frame(minWidth: 44, minHeight: 44)
                .background(selectedDay == day ? Color.blue : Color.white.opacity(0.06), in: Capsule())
                .foregroundStyle(selectedDay == day ? Color.white : Color.secondary)
        }
        .buttonStyle(.plain).accessibilityLabel(SchedulePresentation.weekdays[day])
        .accessibilityValue(selectedDay == day ? "Selected" : "Not selected")
        .accessibilityIdentifier("schedule-filter-\(day)")
    }

    private var calendarBody: some View {
        ScrollViewReader { proxy in
            ScrollView {
                calendarGrid
                Text("Tap a block to change its times, mode, or repeat days. Tap empty space to add one.")
                    .font(.footnote).foregroundStyle(.secondary).padding(.horizontal, 20)
                Text("Outside these blocks, your ticker uses its usual settings.")
                    .font(.footnote).foregroundStyle(.secondary).padding(20)
            }
            .refreshable { await refreshSchedule() }
            .onAppear { proxy.scrollTo("schedule-hour-7", anchor: .top) }
            .onChange(of: selectedDay) { _, _ in proxy.scrollTo("schedule-hour-7", anchor: .top) }
            .onChange(of: scope) { _, _ in proxy.scrollTo("schedule-hour-7", anchor: .top) }
        }
    }

    private var calendarGrid: some View {
        GeometryReader { geometry in
            ZStack(alignment: .topLeading) {
                VStack(spacing: 0) {
                    ForEach(0..<24, id: \.self) { hour in hourRow(hour).id("schedule-hour-\(hour)") }
                }
                ForEach(Array(columns.enumerated()), id: \.element.id) { index, column in
                    ForEach(SchedulePresentation.calendarPlacements(column.blocks(schedule?.blocks ?? []),
                        minimumMinutes: scope == .days ? 45 : 60)) { placement in
                        calendarBlock(placement, column: column, index: index, width: geometry.size.width)
                    }
                }
            }
        }
        .frame(height: hourHeight * 25).padding(.trailing, 16)
    }

    private func hourRow(_ hour: Int) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(SchedulePresentation.hourLabel(hour)).font(.caption2).foregroundStyle(.secondary)
                .frame(width: 48, alignment: .trailing).offset(y: -7)
            HStack(spacing: 0) {
                ForEach(columns) { column in
                    ScheduleEmptyCalendarCell(column: column, hour: hour, hourHeight: hourHeight) { minute in
                        addSchedule(start: minute, days: column.days)
                    }
                }
            }
        }.frame(height: hourHeight)
    }

    private func calendarBlock(_ placement: ScheduleCalendarPlacement, column: ScheduleCalendarColumn,
                               index: Int, width: CGFloat) -> some View {
        let block = placement.block
        let dayWidth = max(1, width - 56) / CGFloat(columns.count)
        let laneWidth = dayWidth / CGFloat(placement.columns)
        let height = CGFloat(placement.visualEnd - block.start_minute) / 60 * hourHeight
        return Button { edit(block) } label: {
            ScheduleCalendarBlockContent(block: block, showRepeat: scope != .days)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .frame(width: max(1, laneWidth - 4), height: max(1, height - 3), alignment: .topLeading)
        .offset(x: 56 + CGFloat(index) * dayWidth + CGFloat(placement.column) * laneWidth,
                y: CGFloat(block.start_minute) / 60 * hourHeight)
        .accessibilityLabel("\(SchedulePresentation.modeName(block.mode)), \(block.timeLabel), \(block.dayLabel)")
        .accessibilityValue(block.enabled ? "Enabled" : "Disabled")
        .accessibilityHint("Edit schedule")
        .accessibilityIdentifier("schedule-edit-\(block.id)-\(column.id)")
    }

    private var calendarControls: some View {
        HStack {
            liveRuleControl
            Spacer(minLength: 0)
            if schedule?.effective.has_enabled_rules == true {
              Button { setOverride(!(schedule?.effective.override ?? false)) } label: {
                Label(schedule?.effective.override == true ? "Resume schedule" : "Pause schedule",
                      systemImage: schedule?.effective.override == true ? "play.circle" : "pause.circle")
                    .font(.subheadline.weight(.medium)).frame(minHeight: 44)
            }.tint(.orange).disabled(updatingOverride).accessibilityIdentifier("schedule-override")
            }
        }
        .padding(.horizontal, 20).padding(.vertical, 5).background(.ultraThinMaterial)
    }

    @ViewBuilder private var liveRuleControl: some View {
        if let conditions = schedule?.conditions, conditions.count > 1 {
            Menu {
                ForEach(conditions) { condition in
                    Button(condition.label) { conditionEditor = ScheduleConditionSelection(condition: condition) }
                }
            } label: { liveRuleLabel }.accessibilityIdentifier("schedule-rules")
        } else {
            Button {
                conditionEditor = ScheduleConditionSelection(condition: schedule?.conditions.first)
            } label: { liveRuleLabel }.accessibilityIdentifier("schedule-rules")
        }
    }

    private var liveRuleLabel: some View {
        Label("Live sports rule", systemImage: "bolt.fill").font(.subheadline.weight(.medium)).frame(minHeight: 44)
    }

    private var scheduleBackground: some View {
        LinearGradient(colors: [Color(red: 0.14, green: 0.19, blue: 0.25), Color(red: 0.04, green: 0.06, blue: 0.09)],
                       startPoint: .top, endPoint: .bottom).ignoresSafeArea()
    }

    private func addSchedule(start: Int = 480, days: [Int]? = nil) {
        blockEditor = ScheduleBlockSelection(block: nil, days: days ?? columns[0].days, start: start)
    }
    private func edit(_ block: TickerScheduleBlock) {
        blockEditor = ScheduleBlockSelection(block: block, days: block.days_of_week, start: block.start_minute)
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
                if schedule == nil, (0...6).contains(value.effective.day_of_week) { selectedDay = value.effective.day_of_week }
                schedule = value
                errorMessage = nil
            case .failure(let error): errorMessage = error.localizedDescription
            }
        }
    }

    private func refreshSchedule() async {
        await withCheckedContinuation { continuation in loadSchedule { continuation.resume() } }
    }

    private func setOverride(_ enabled: Bool) {
        updatingOverride = true
        vm.setScheduleOverride(tickerID: device.id, enabled: enabled) { result in
            updatingOverride = false
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
    let days: [Int]
    let start: Int
}

private struct ScheduleConditionSelection: Identifiable {
    let id = UUID()
    let condition: TickerScheduleCondition?
}

private struct ScheduleEmptyCalendarCell: View {
    let column: ScheduleCalendarColumn
    let hour: Int
    let hourHeight: CGFloat
    let tap: (Int) -> Void

    var body: some View {
        VStack(spacing: 0) {
            ForEach(0..<4, id: \.self) { quarter in
                Rectangle().fill(Color.white.opacity(quarter == 0 ? 0.12 : 0.035)).frame(height: 1)
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity)
        .background(alignment: .leading) { Rectangle().fill(Color.white.opacity(0.08)).frame(width: 1) }
        .contentShape(Rectangle())
        .gesture(SpatialTapGesture().onEnded { value in
            tap(ScheduleCalendarColumn.minute(hour: hour, fraction: Double(value.location.y / hourHeight)))
        })
        .accessibilityElement().accessibilityLabel("Add schedule at \(SchedulePresentation.clock(hour * 60))")
        .accessibilityAddTraits(.isButton).accessibilityAction { tap(hour * 60) }
        .accessibilityIdentifier("schedule-add-hour-\(hour)-\(column.id)")
    }
}

private struct ScheduleCalendarBlockContent: View {
    let block: TickerScheduleBlock
    let showRepeat: Bool
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
    private func shortClock(_ minute: Int) -> String {
        let hour = (minute / 60) % 24
        let display = hour % 12 == 0 ? 12 : hour % 12
        let fraction = minute % 60 == 0 ? "" : String(format: ":%02d", minute % 60)
        return "\(display)\(fraction)\(hour >= 12 ? "PM" : "AM")"
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(SchedulePresentation.modeName(block.mode)).font(.caption.weight(.semibold)).lineLimit(3)
            Text("\(shortClock(block.start_minute))–\(shortClock(block.end_minute))").font(.caption2).lineLimit(2)
            if showRepeat { Text(block.dayLabel).font(.caption2).foregroundStyle(.white.opacity(0.8)) }
            if !block.enabled { Text("Off").font(.caption2).foregroundStyle(.secondary) }
            Spacer(minLength: 0)
        }
        .foregroundStyle(.white).padding(.horizontal, 6).padding(.vertical, 6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(color.opacity(block.enabled ? 0.3 : 0.08), in: RoundedRectangle(cornerRadius: 6))
        .overlay(alignment: .leading) { RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 3) }
        .overlay {
            RoundedRectangle(cornerRadius: 6).strokeBorder(color.opacity(0.65),
                style: StrokeStyle(lineWidth: 1, dash: block.enabled ? [] : [4, 3]))
        }.opacity(block.enabled ? 1 : 0.55)
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
    @State private var confirmingDelete = false

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
                if block != nil {
                    Section {
                        Button("Delete schedule", role: .destructive) { confirmingDelete = true }
                            .disabled(isSaving).accessibilityIdentifier("schedule-editor-delete")
                    }
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
            .alert("Delete this schedule?", isPresented: $confirmingDelete) {
                Button("Cancel", role: .cancel) {}
                Button("Delete schedule", role: .destructive, action: delete)
            } message: {
                if let block { Text("\(SchedulePresentation.modeName(block.mode)) · \(block.dayLabel) · \(block.timeLabel)") }
            }
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
            HStack {
                Text("Starts")
                Spacer()
                ScheduleTimePicker(date: $startDate, timeZone: timeZone).frame(width: 140, height: 36)
                    .accessibilityIdentifier("schedule-start-time")
            }
            HStack {
                Text("Ends")
                Spacer()
                ScheduleTimePicker(date: $endDate, timeZone: timeZone).frame(width: 140, height: 36)
                    .accessibilityIdentifier("schedule-end-time")
            }
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

    private func delete() {
        guard let block else { return }
        isSaving = true
        errorMessage = nil
        vm.deleteScheduleBlock(tickerID: tickerID, blockID: block.id) { result in
            isSaving = false
            switch result {
            case .success: onSaved(); isPresented = false
            case .failure(let error): errorMessage = error.localizedDescription
            }
        }
    }
}

private struct ScheduleTimePicker: UIViewRepresentable {
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

private struct ScheduleConditionEditor: View {
    @ObservedObject var vm: TickerViewModel
    let tickerID: String
    let condition: TickerScheduleCondition?
    let liveGames: Int
    @Binding var isPresented: Bool
    let onSaved: () -> Void
    @State private var threshold: Int
    @State private var comparison: String
    @State private var enabled: Bool
    @State private var errorMessage: String?
    @State private var isSaving = false
    @State private var confirmingDelete = false

    init(vm: TickerViewModel, tickerID: String, condition: TickerScheduleCondition?, liveGames: Int,
         isPresented: Binding<Bool>, onSaved: @escaping () -> Void) {
        self.vm = vm; self.tickerID = tickerID; self.condition = condition; self.onSaved = onSaved
        self.liveGames = liveGames
        _isPresented = isPresented
        _threshold = State(initialValue: condition?.threshold ?? 5)
        _comparison = State(initialValue: condition?.operator ?? "gt")
        _enabled = State(initialValue: condition?.enabled ?? true)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("Show only live games", systemImage: "sportscourt.fill").font(.headline)
                    Text("Your ticker switches its sports feed when enough games are live.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    Text("\(liveGames) live \(liveGames == 1 ? "game" : "games") on this ticker")
                        .font(.subheadline).foregroundStyle(.secondary)
                        .accessibilityIdentifier("schedule-live-count")
                }
                Section("When games are live") {
                    Picker("Number of games", selection: $comparison) {
                        Text("At least").tag("gte")
                        Text("More than").tag("gt")
                    }.pickerStyle(.segmented).accessibilityIdentifier("schedule-condition-comparison")
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
