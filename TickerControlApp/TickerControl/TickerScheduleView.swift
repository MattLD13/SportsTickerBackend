import SwiftUI

struct TickerScheduleView: View {
    @ObservedObject var vm: TickerViewModel
    let device: TickerDevice
    @Binding var isPresented: Bool

    @State private var schedule: TickerScheduleResponse?
    @State private var selectedMode = "sports"
    @State private var selectedDays: Set<Int> = [0]
    @State private var editingBlock: TickerScheduleBlock?
    @State private var editingCondition: TickerScheduleCondition?
    @State private var showingBlockEditor = false
    @State private var showingConditionEditor = false
    @State private var isLoading = false
    @State private var errorMessage: String?

    private var tickerTimeZone: TimeZone {
        TimeZone(identifier: schedule?.timezone ?? "") ?? .current
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
            ScrollView(.vertical, showsIndicators: false) {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Weekly schedule")
                                    .font(.title3.bold())
                                Text(timezoneLabel)
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }
                            Spacer()
                            Image(systemName: "calendar.badge.clock")
                                .font(.title2)
                                .foregroundColor(.blue)
                        }
                        Text("Choose a day group, then drag blocks vertically. Drag either edge to resize in 15-minute steps.")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .liquidGlass()

                    ScheduleTimelineView(
                        schedule: schedule,
                        supportedModes: supportedModes,
                        selectedDays: $selectedDays,
                        selectedMode: $selectedMode,
                        onCreate: createBlock,
                        onEdit: { block in
                            editingBlock = block
                            showingBlockEditor = true
                        },
                        onDelete: deleteBlock,
                        onUpdate: updateBlock
                    )
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .liquidGlass()

                    VStack(alignment: .leading, spacing: 12) {
                        Text("Conditions")
                            .font(.headline)
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
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .liquidGlass()

                    VStack(alignment: .leading, spacing: 12) {
                        Text("Ticker override")
                            .font(.headline)
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
                        Text("An override expires at the next schedule transition, then recurring rules resume.")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .liquidGlass()

                    if let errorMessage {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundColor(.red)
                            .padding(16)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .liquidGlass()
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
            .background(Color.black.opacity(0.18).ignoresSafeArea())
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
        .presentationDetents([.large])
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

    private func createBlock(days: [Int], startMinute: Int, mode: String) {
        let start = min(1380, max(0, (startMinute / 15) * 15))
        vm.createScheduleBlock(
            tickerID: device.id,
            daysOfWeek: days,
            startMinute: start,
            endMinute: min(1440, start + 60),
            mode: mode,
            sportsFilter: mode == "sports" ? "all" : nil
        ) { result in
            switch result {
            case .success:
                loadSchedule()
            case .failure(let error):
                errorMessage = error.localizedDescription
            }
        }
    }

    private func updateBlock(
        _ block: TickerScheduleBlock,
        daysOfWeek: [Int],
        startMinute: Int,
        endMinute: Int
    ) {
        vm.updateScheduleBlock(
            tickerID: device.id,
            blockID: block.id,
            daysOfWeek: daysOfWeek,
            startMinute: startMinute,
            endMinute: endMinute,
            mode: block.mode,
            sportsFilter: block.sports_filter,
            enabled: block.enabled
        ) { result in
            switch result {
            case .success:
                loadSchedule()
            case .failure(let error):
                errorMessage = error.localizedDescription
                loadSchedule()
            }
        }
    }
}

private struct ScheduleTimelineView: View {
    private static let dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    private static let minuteHeight: CGFloat = 0.8
    private static let timelineHeight: CGFloat = 1152
    private static let timeGutter: CGFloat = 52
    private static let cycleCount = 5
    private static let centerCycle = 2
    private static let nowAnchorID = "schedule-now-anchor"
    private static let minimumBlockMinutes = 15

    let schedule: TickerScheduleResponse?
    let supportedModes: [String]
    @Binding var selectedDays: Set<Int>
    @Binding var selectedMode: String
    let onCreate: ([Int], Int, String) -> Void
    let onEdit: (TickerScheduleBlock) -> Void
    let onDelete: (TickerScheduleBlock) -> Void
    let onUpdate: (TickerScheduleBlock, [Int], Int, Int) -> Void

    @State private var interaction: TimelineInteraction?
    @State private var gestureStart: TimelineInteraction?

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            scheduleContent(currentDate: context.date)
        }
    }

    private func scheduleContent(currentDate: Date) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            dayChooser

            modePalette

            verticalTimeline(currentDate: currentDate)
            .frame(height: 500)
            .background(Color.black.opacity(0.18))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            }
            .scrollIndicators(.visible)

            Text("Tap an empty time or drag a mode into it to add a one-hour block. Drag a block to move it, or use either edge to resize it.")
                .font(.caption)
                .foregroundColor(.secondary)
        }
    }

    private var dayChooser: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Apply blocks to")
                .font(.subheadline.bold())
                .foregroundColor(.secondary)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 7), spacing: 6) {
                ForEach(0..<7, id: \.self) { day in
                    dayButton(Self.dayNames[day], days: [day])
                }
            }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 3), spacing: 6) {
                dayButton("Weekdays", days: Array(0...4))
                dayButton("Weekends", days: Array(5...6))
                dayButton("Every day", days: Array(0...6))
            }
        }
    }

    private func dayButton(_ title: String, days: [Int]) -> some View {
        Button {
            selectedDays = Set(days)
        } label: {
            Text(title)
                .font(.caption.bold())
                .lineLimit(1)
                .minimumScaleFactor(0.8)
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity)
                .foregroundColor(selectedDays == Set(days) ? .white : .primary)
                .background(selectedDays == Set(days) ? Color.blue.opacity(0.8) : Color.white.opacity(0.08))
                .overlay {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(selectedDays == Set(days) ? Color.blue : Color.white.opacity(0.08), lineWidth: 1)
                }
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
    }

    private var modePalette: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Drag a mode onto the timeline")
                .font(.subheadline.bold())
                .foregroundColor(.secondary)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(supportedModes, id: \.self) { mode in
                        Button {
                            selectedMode = mode
                        } label: {
                            Label(mode.capitalized, systemImage: modeIcon(mode))
                                .font(.caption.bold())
                                .lineLimit(1)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 9)
                                .foregroundColor(selectedMode == mode ? .white : .primary)
                                .background(selectedMode == mode ? modeColor(mode).opacity(0.8) : Color.white.opacity(0.08))
                                .clipShape(Capsule())
                        }
                        .buttonStyle(.plain)
                        .draggable(mode)
                    }
                }
            }
        }
    }

    private func verticalTimeline(currentDate: Date) -> some View {
        ScrollViewReader { proxy in
            ScrollView(.vertical) {
                VStack(spacing: 0) {
                    ForEach(0..<Self.cycleCount, id: \.self) { cycle in
                        timelineCanvas(currentDate: cycle == Self.centerCycle ? currentDate : nil)
                            .id("schedule-cycle-\(cycle)")
                    }
                }
            }
            .scrollIndicators(.visible)
            .onAppear {
                DispatchQueue.main.async {
                    proxy.scrollTo(Self.nowAnchorID, anchor: .center)
                }
            }
            .onScrollGeometryChange(for: CGFloat.self) { geometry in
                geometry.contentOffset.y
            } action: { _, offset in
                let cycleHeight = Self.timelineHeight
                if offset < cycleHeight * 0.65 || offset > cycleHeight * 3.35 {
                    DispatchQueue.main.async {
                        proxy.scrollTo(Self.nowAnchorID, anchor: .center)
                    }
                }
            }
        }
    }

    private func timelineCanvas(currentDate: Date?) -> some View {
        GeometryReader { proxy in
            let trackWidth = max(1, proxy.size.width - Self.timeGutter)
            HStack(spacing: 0) {
                timeLabels
                    .frame(width: Self.timeGutter, height: Self.timelineHeight)
                ZStack(alignment: .topLeading) {
                    verticalGrid(width: trackWidth)
                        .contentShape(Rectangle())
                        .gesture(SpatialTapGesture().onEnded { value in
                            let minute = max(0, min(1440, minute(for: value.location.y)))
                            onCreate(Array(selectedDays).sorted(), snapMinute(minute), selectedMode)
                        })
                    if let currentDate, let currentMinute = currentMinute(at: currentDate) {
                        currentTimeIndicator(minute: currentMinute, width: trackWidth)
                            .id(Self.nowAnchorID)
                    }
                    ForEach(occurrences()) { occurrence in
                        timelineBlock(occurrence, width: trackWidth)
                    }
                }
                .frame(width: trackWidth, height: Self.timelineHeight)
                .contentShape(Rectangle())
                .dropDestination(for: String.self) { items, location in
                    guard let mode = items.first, supportedModes.contains(mode) else { return false }
                    let minute = max(0, min(1440, minute(for: location.y)))
                    onCreate(Array(selectedDays).sorted(), snapMinute(minute), mode)
                    return true
                }
            }
        }
        .frame(height: Self.timelineHeight)
    }

    private func verticalGrid(width: CGFloat) -> some View {
        ZStack(alignment: .topLeading) {
            Color.white.opacity(0.035)
            ForEach(0...48, id: \.self) { index in
                Rectangle()
                    .fill(Color.white.opacity(index % 2 == 0 ? 0.2 : 0.07))
                    .frame(width: width, height: 1)
                    .offset(y: y(for: index * 30))
            }
        }
    }

    private var timeLabels: some View {
        ZStack(alignment: .topLeading) {
            ForEach(0...24, id: \.self) { index in
                Text(Self.clock(index * 60))
                    .font(.caption2.monospacedDigit())
                    .foregroundColor(.secondary)
                    .frame(width: Self.timeGutter - 8, alignment: .trailing)
                    .offset(y: y(for: index * 60) - 7)
            }
        }
        .frame(width: Self.timeGutter, height: Self.timelineHeight, alignment: .topLeading)
        .background(Color.black.opacity(0.08))
        .clipped()
    }

    private func currentTimeIndicator(minute: Int, width: CGFloat) -> some View {
        HStack(spacing: 0) {
            Circle()
                .fill(Color.green)
                .frame(width: 8, height: 8)
                .offset(x: -4)
            Rectangle()
                .fill(Color.green)
                .frame(width: width, height: 2)
        }
        .offset(y: y(for: minute) - 1)
        .allowsHitTesting(false)
        .zIndex(10)
    }

    private func occurrences() -> [TimelineOccurrence] {
        guard let blocks = schedule?.blocks else { return [] }
        let days = selectedDays
        var result: [TimelineOccurrence] = []
        for block in blocks {
            let preview = interaction?.blockID == block.id ? interaction : nil
            if let preview {
                result.append(TimelineOccurrence(
                    id: block.id,
                    block: block,
                    startMinute: preview.startMinute,
                    endMinute: preview.endMinute,
                    isPreview: true
                ))
                continue
            }
            let matchesSelection = days.count == 1
                ? block.days_of_week.contains(days.first!)
                : Set(block.days_of_week) == days
            if matchesSelection {
                result.append(TimelineOccurrence(
                    id: block.id,
                    block: block,
                    startMinute: block.start_minute,
                    endMinute: block.end_minute,
                    isPreview: false
                ))
            }
        }
        return result.sorted { $0.startMinute < $1.startMinute }
    }

    private func timelineBlock(_ occurrence: TimelineOccurrence, width: CGFloat) -> some View {
        let duration = occurrence.endMinute - occurrence.startMinute
        let blockHeight = max(40, CGFloat(duration) * Self.minuteHeight - 4)
        return VStack(spacing: 0) {
            resizeHandle(edge: .start, occurrence: occurrence)
            HStack(spacing: 4) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(occurrence.block.mode.capitalized)
                        .font(.caption.bold())
                        .lineLimit(1)
                    Text("\(Self.clock(occurrence.startMinute))–\(Self.clock(occurrence.endMinute))")
                        .font(.caption2.monospacedDigit())
                        .lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Menu {
                    Button("Edit", action: { onEdit(occurrence.block) })
                    Button("Delete", role: .destructive, action: { onDelete(occurrence.block) })
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.caption.bold())
                        .frame(width: 28, height: 30)
                }
                .menuStyle(.borderlessButton)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .gesture(moveGesture(occurrence))
            resizeHandle(edge: .end, occurrence: occurrence)
        }
        .padding(.horizontal, 4)
        .frame(width: max(0, width - 12), height: blockHeight)
        .foregroundColor(.white)
        .background(modeColor(occurrence.block.mode).opacity(occurrence.block.enabled ? 0.82 : 0.35))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(modeColor(occurrence.block.mode), lineWidth: occurrence.isPreview ? 2 : 1))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .offset(x: 6, y: y(for: occurrence.startMinute) + 2)
        .opacity(occurrence.block.enabled ? 1 : 0.55)
    }

    private func resizeHandle(edge: ResizeEdge, occurrence: TimelineOccurrence) -> some View {
        Capsule()
            .fill(Color.white.opacity(0.8))
            .frame(maxWidth: .infinity, minHeight: 10, maxHeight: 10)
            .padding(.horizontal, 8)
            .contentShape(Rectangle())
            .gesture(resizeGesture(occurrence, edge: edge))
    }

    private func moveGesture(_ occurrence: TimelineOccurrence) -> some Gesture {
        DragGesture(minimumDistance: 4)
            .onChanged { value in
                let base: TimelineInteraction
                if let gestureStart, gestureStart.blockID == occurrence.block.id {
                    base = gestureStart
                } else {
                    base = TimelineInteraction(
                        blockID: occurrence.block.id,
                        startMinute: occurrence.startMinute,
                        endMinute: occurrence.endMinute
                    )
                    self.gestureStart = base
                }
                let duration = base.endMinute - base.startMinute
                let delta = snapMinute(minute(for: value.translation.height))
                let nextStart = max(0, min(1440 - duration, base.startMinute + delta))
                interaction = TimelineInteraction(
                    blockID: occurrence.block.id,
                    startMinute: nextStart,
                    endMinute: nextStart + duration
                )
            }
            .onEnded { _ in
                finishInteraction(for: occurrence)
            }
    }

    private func resizeGesture(_ occurrence: TimelineOccurrence, edge: ResizeEdge) -> some Gesture {
        DragGesture(minimumDistance: 2)
            .onChanged { value in
                let base: TimelineInteraction
                if let gestureStart, gestureStart.blockID == occurrence.block.id {
                    base = gestureStart
                } else {
                    base = TimelineInteraction(
                        blockID: occurrence.block.id,
                        startMinute: occurrence.startMinute,
                        endMinute: occurrence.endMinute
                    )
                    self.gestureStart = base
                }
                var start = base.startMinute
                var end = base.endMinute
                let minuteDelta = snapMinute(minute(for: value.translation.height))
                if edge == .start {
                    start = max(0, min(end - Self.minimumBlockMinutes, base.startMinute + minuteDelta))
                } else {
                    end = min(1440, max(start + Self.minimumBlockMinutes, base.endMinute + minuteDelta))
                }
                interaction = TimelineInteraction(
                    blockID: occurrence.block.id,
                    startMinute: start,
                    endMinute: end
                )
            }
            .onEnded { _ in
                finishInteraction(for: occurrence)
            }
    }

    private func finishInteraction(for occurrence: TimelineOccurrence) {
        guard let interaction,
              let gestureStart,
              interaction.blockID == occurrence.block.id,
              gestureStart.blockID == occurrence.block.id else { return }
        defer {
            self.interaction = nil
            self.gestureStart = nil
        }
        guard interaction.startMinute != gestureStart.startMinute || interaction.endMinute != gestureStart.endMinute else { return }
        onUpdate(occurrence.block, occurrence.block.days_of_week, interaction.startMinute, interaction.endMinute)
    }

    private func snapMinute(_ value: Int) -> Int {
        Int((Double(value) / 15.0).rounded()) * 15
    }

    private func minute(for y: CGFloat) -> Int {
        Int((y / Self.minuteHeight).rounded())
    }

    private func y(for minute: Int) -> CGFloat {
        CGFloat(max(0, min(1440, minute))) * Self.minuteHeight
    }

    private func currentMinute(at date: Date) -> Int? {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: schedule?.timezone ?? "") ?? .current
        let hour = calendar.component(.hour, from: date)
        let minute = calendar.component(.minute, from: date)
        return hour * 60 + minute
    }

    private func modeIcon(_ mode: String) -> String {
        [
            "sports": "sportscourt.fill",
            "stock": "chart.line.uptrend.xyaxis",
            "weather": "cloud.sun.fill",
            "music": "music.note",
            "flights": "airplane",
            "airports": "building.2.fill",
            "clock": "clock.fill",
        ][mode, default: "circle"]
    }

    private func modeColor(_ mode: String) -> Color {
        [
            "sports": .green,
            "stock": .orange,
            "weather": .cyan,
            "music": .purple,
            "flights": .yellow,
            "airports": .blue,
            "clock": .gray,
        ][mode, default: .blue]
    }

    private static func clock(_ minute: Int) -> String {
        let normalizedMinute = minute == 1440 ? 0 : minute
        let hour = (normalizedMinute / 60) % 24
        let displayHour = hour % 12 == 0 ? 12 : hour % 12
        let meridiem = hour < 12 ? "AM" : "PM"
        return String(format: "%d:%02d %@", displayHour, normalizedMinute % 60, meridiem)
    }

    private enum ResizeEdge {
        case start
        case end
    }

    private struct TimelineInteraction {
        let blockID: String
        let startMinute: Int
        let endMinute: Int
    }

    private struct TimelineOccurrence: Identifiable {
        let id: String
        let block: TickerScheduleBlock
        let startMinute: Int
        let endMinute: Int
        let isPreview: Bool
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
