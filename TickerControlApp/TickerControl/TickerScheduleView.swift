import SwiftUI
import UIKit

struct TickerScheduleView: View {
    @ObservedObject var vm: TickerViewModel
    let device: TickerDevice
    @Binding var isPresented: Bool

    @State private var schedule: TickerScheduleResponse?
    @State private var selectedDay = 0
    @State private var dayCount = 3
    @State private var selectedBlockID: String?
    @State private var calendarDraft: ScheduleCalendarDraft?
    @State private var repeatChange: ScheduleCalendarDraft?
    @State private var dragging = false
    @State private var newRange: ScheduleBlockSelection?
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
    private var visibleDays: [Int] { ScheduleCalendarInteraction.days(start: selectedDay, count: dayCount) }
    private var selectedBlock: TickerScheduleBlock? {
        schedule?.blocks.first { $0.id == selectedBlockID }
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
                    initialDays: [selection.day], initialStart: selection.start, initialEnd: selection.end,
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
            .alert("Change repeating schedule?", isPresented: Binding(
                get: { repeatChange != nil }, set: { if !$0 { repeatChange = nil } }
            ), presenting: repeatChange) { change in
                Button("Apply to all repeat days") { commit(change) }
                Button("Cancel", role: .cancel) { calendarDraft = nil }
            } message: { change in
                Text("\(change.proposed.dayLabel) · \(change.proposed.timeLabel). This changes the whole repeating schedule.")
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
            HStack(spacing: 12) {
                Picker("Calendar view", selection: $dayCount) {
                    Text("Day").tag(1)
                    Text("3 days").tag(3)
                }.pickerStyle(.segmented).frame(width: 150)
                    .accessibilityIdentifier("schedule-view-picker")
                Spacer(minLength: 0)
                Button { selectedDay = (selectedDay - dayCount + 7) % 7 } label: {
                    Image(systemName: "chevron.left").frame(width: 36, height: 44)
                }.accessibilityLabel("Previous days")
                Button { selectedDay = (selectedDay + dayCount) % 7 } label: {
                    Image(systemName: "chevron.right").frame(width: 36, height: 44)
                }.accessibilityLabel("Next days")
            }.disabled(dragging)
            if dayCount == 1 {
              ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(0..<7, id: \.self) { day in
                        dayFilter(day)
                    }
                }
              }
            }
            HStack(spacing: 0) {
                Text(tickerTimeZone.abbreviation() ?? "Time").font(.caption2).foregroundStyle(.secondary)
                    .frame(width: 36)
                ForEach(visibleDays, id: \.self) { day in
                    Text(dayCount == 1 ? SchedulePresentation.weekdays[day] : String(SchedulePresentation.weekdays[day].prefix(3)))
                        .font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity)
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
                Text("Hold a block to move it. Tap to select its resize handles. Hold an empty space to draw a block.")
                    .font(.footnote).foregroundStyle(.secondary).padding(.horizontal, 20)
                Text("Outside these blocks, your ticker uses its usual settings.")
                    .font(.footnote).foregroundStyle(.secondary).padding(20)
            }
            .scrollDisabled(dragging)
            .refreshable { if !dragging { await refreshSchedule() } }
            .onAppear { proxy.scrollTo("schedule-hour-7", anchor: .top) }
            .onChange(of: selectedDay) { _, _ in
                selectedBlockID = nil
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
                ForEach(Array(visibleDays.enumerated()), id: \.element) { dayIndex, day in
                    ForEach(SchedulePresentation.calendarPlacements(SchedulePresentation.blocks(schedule?.blocks ?? [], on: day))) { placement in
                        calendarBlock(placement, day: day, dayIndex: dayIndex, width: geometry.size.width)
                    }
                }
                if let calendarDraft {
                    draftBlocks(calendarDraft.proposed, width: geometry.size.width)
                }
                if let newRange {
                    draftBlocks(newBlock(newRange), width: geometry.size.width)
                }
            }
            .coordinateSpace(name: "schedule-grid")
        }
        .frame(height: hourHeight * 24 + hourHeight)
        .padding(.trailing, 16)
        .allowsHitTesting(pending.isEmpty && repeatChange == nil)
    }

    private func hourRow(_ hour: Int) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(SchedulePresentation.hourLabel(hour)).font(.caption2).foregroundStyle(.secondary)
                .frame(width: 48, alignment: .trailing).offset(y: -7)
            HStack(spacing: 0) {
                ForEach(visibleDays, id: \.self) { day in
                    ScheduleEmptyCalendarCell(day: day, hour: hour, hourHeight: hourHeight,
                        tap: { addSchedule(start: min(1425, $0), day: day) },
                        began: { dragging = true },
                        changed: { value in updateCreation(day: day, value: value) },
                        ended: finishCreation, cancelled: cancelGesture)
                }
            }
        }
        .frame(height: hourHeight)
    }

    private func calendarBlock(_ placement: ScheduleCalendarPlacement, day: Int, dayIndex: Int, width: CGFloat) -> some View {
        let block = placement.block
        let availableWidth = max(1, width - 56) / CGFloat(dayCount)
        let columnWidth = availableWidth / CGFloat(placement.columns)
        let duration = selectedBlockID == block.id ? max(15, block.end_minute - block.start_minute) : placement.visualEnd - block.start_minute
        let height = CGFloat(duration) / 60 * hourHeight
        return ScheduleCalendarBlock(block: block, occurrenceDay: day,
            pending: pending.contains(block.id), selected: selectedBlockID == block.id,
            select: { selectedBlockID = block.id }, edit: { edit(block) },
            began: {
                dragging = true
                selectedBlockID = block.id
                calendarDraft = ScheduleCalendarDraft(original: block, proposed: block)
            },
            changed: { operation, value in
                updateGesture(block, operation: operation, value: value, columnWidth: availableWidth, from: dayIndex)
            },
            ended: finishGesture, cancelled: cancelGesture)
            .frame(width: max(1, columnWidth - 4), height: max(1, height - 3), alignment: .topLeading)
            .opacity(calendarDraft?.original.id == block.id ? 0.25 : 1)
            .offset(x: 56 + CGFloat(dayIndex) * availableWidth + CGFloat(placement.column) * columnWidth,
                    y: CGFloat(block.start_minute) / 60 * hourHeight)
            .zIndex(selectedBlockID == block.id ? 2 : 0)
    }

    private var calendarControls: some View {
      VStack(spacing: 3) {
        if let selectedBlock {
            HStack {
                Button("Edit mode & days") { edit(selectedBlock) }
                    .accessibilityIdentifier("schedule-selected-edit")
                Menu {
                    Button(selectedBlock.enabled ? "Turn off" : "Turn on", systemImage: "power") {
                        setEnabled(selectedBlock, !selectedBlock.enabled)
                    }
                    Button("Delete schedule", systemImage: "trash", role: .destructive) {
                        blockToDelete = selectedBlock
                    }
                } label: {
                    Image(systemName: "ellipsis.circle").frame(width: 44, height: 44)
                }.accessibilityLabel("Schedule actions").accessibilityIdentifier("schedule-selected-more")
                Spacer()
                Button("Done") { selectedBlockID = nil }
            }.font(.subheadline).padding(.horizontal, 20)
            Text("\(calendarDraft?.proposed.dayLabel ?? selectedBlock.dayLabel) · \(calendarDraft?.proposed.timeLabel ?? selectedBlock.timeLabel)")
                .font(.caption).foregroundStyle(.secondary)
        }
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
      }.disabled(dragging)
    }

    private var scheduleBackground: some View {
        LinearGradient(colors: [Color(red: 0.14, green: 0.19, blue: 0.25), Color(red: 0.04, green: 0.06, blue: 0.09)],
                       startPoint: .top, endPoint: .bottom).ignoresSafeArea()
    }

    private func addSchedule(start: Int = 480, day: Int? = nil) {
        blockEditor = ScheduleBlockSelection(block: nil, day: day ?? selectedDay, start: start)
    }
    private func edit(_ block: TickerScheduleBlock) {
        blockEditor = ScheduleBlockSelection(block: block, day: selectedDay, start: block.start_minute)
    }
    private func scheduleChanged() { loadSchedule(); vm.fetchData() }

    private func updateGesture(_ block: TickerScheduleBlock, operation: ScheduleCalendarEdit,
                               value: DragGesture.Value, columnWidth: CGFloat, from column: Int) {
        guard !pending.contains(block.id) else { return }
        dragging = true
        selectedBlockID = block.id
        let offset = operation == .move ? ScheduleCalendarInteraction.columnOffset(
            translation: Double(value.translation.width), width: Double(columnWidth), column: column, count: dayCount) : 0
        let proposed = ScheduleCalendarInteraction.applying(operation, to: block,
            minutes: Double(value.translation.height / hourHeight * 60), dayOffset: offset)
        calendarDraft = ScheduleCalendarDraft(original: block, proposed: proposed)
    }

    private func finishGesture() {
        dragging = false
        guard let change = calendarDraft else { return }
        guard ScheduleCalendarInteraction.hasChanges(change.original, change.proposed) else {
            calendarDraft = nil
            return
        }
        if change.original.days_of_week.count > 1 { repeatChange = change } else { commit(change) }
    }

    private func cancelGesture() {
        guard dragging else { return }
        dragging = false
        calendarDraft = nil
        newRange = nil
    }

    private func commit(_ change: ScheduleCalendarDraft) {
        let block = change.proposed
        pending.insert(block.id)
        vm.updateScheduleBlock(tickerID: device.id, blockID: block.id, daysOfWeek: block.days_of_week,
            startMinute: block.start_minute, endMinute: block.end_minute, mode: block.mode,
            sportsFilter: block.sports_filter, enabled: block.enabled) { result in
                switch result {
                case .success:
                    loadSchedule { pending.remove(block.id); calendarDraft = nil }
                    vm.fetchData()
                case .failure(let error):
                    pending.remove(block.id)
                    calendarDraft = nil
                    errorMessage = error.localizedDescription
                }
            }
    }

    private func updateCreation(day: Int, value: DragGesture.Value) {
        dragging = true
        let range = ScheduleCalendarInteraction.drawnRange(first: Double(value.startLocation.y / hourHeight * 60),
            last: Double(value.location.y / hourHeight * 60))
        newRange = ScheduleBlockSelection(block: nil, day: day, start: range.start, end: range.end)
    }

    private func finishCreation() {
        dragging = false
        blockEditor = newRange
        newRange = nil
    }

    private func newBlock(_ selection: ScheduleBlockSelection) -> TickerScheduleBlock {
        let mode = supportedModes.first ?? "sports"
        return TickerScheduleBlock(id: "new-selection", ticker_id: device.id, days_of_week: [selection.day],
            day_names: [], start_minute: selection.start, end_minute: selection.end ?? min(1440, selection.start + 60),
            mode: mode, sports_filter: mode == "sports" ? "all" : nil, enabled: true, created_at: 0, updated_at: 0)
    }

    private func draftBlocks(_ block: TickerScheduleBlock, width: CGFloat) -> some View {
        let columnWidth = max(1, width - 56) / CGFloat(dayCount)
        return ForEach(Array(visibleDays.enumerated()), id: \.element) { index, day in
            if block.days_of_week.contains(day) {
                ScheduleCalendarBlockContent(block: block, pending: false, selected: true)
                    .frame(width: columnWidth - 4, height: CGFloat(max(15, block.end_minute - block.start_minute)) / 60 * hourHeight - 3)
                    .offset(x: 56 + CGFloat(index) * columnWidth, y: CGFloat(block.start_minute) / 60 * hourHeight)
                    .allowsHitTesting(false).accessibilityHidden(true).zIndex(3)
            }
        }
    }

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
    var end: Int? = nil
}

private struct ScheduleCalendarDraft {
    let original: TickerScheduleBlock
    let proposed: TickerScheduleBlock
}

private struct ScheduleConditionSelection: Identifiable {
    let id = UUID()
    let condition: TickerScheduleCondition?
}

private struct ScheduleCalendarBlock: View {
    let block: TickerScheduleBlock
    let occurrenceDay: Int
    let pending: Bool
    let selected: Bool
    let select: () -> Void
    let edit: () -> Void
    let began: () -> Void
    let changed: (ScheduleCalendarEdit, DragGesture.Value) -> Void
    let ended: () -> Void
    let cancelled: () -> Void
    @GestureState private var held = false

    var body: some View {
        ScheduleCalendarBlockContent(block: block, pending: pending, selected: selected)
            .contentShape(Rectangle())
            .onTapGesture(perform: select)
            .simultaneousGesture(LongPressGesture(minimumDuration: 0.35)
                .sequenced(before: DragGesture(minimumDistance: 1, coordinateSpace: .named("schedule-grid")))
                .updating($held) { _, state, _ in state = true }
                .onChanged { value in
                    switch value {
                    case .first(true), .second(true, nil): began()
                    case .second(true, let drag?): changed(.move, drag)
                    default: break
                    }
                }
                .onEnded { value in
                    if case .second(true, .some) = value { ended() } else { cancelled() }
                })
            .overlay(alignment: .topLeading) {
                if selected && !pending { resizeHandle(.start).offset(y: -22) }
            }
            .overlay(alignment: .bottomTrailing) {
                if selected && !pending { resizeHandle(.end).offset(y: 22) }
            }
            .onChange(of: held) { _, active in if !active { cancelled() } }
            .allowsHitTesting(!pending)
            .accessibilityElement(children: .contain)
            .accessibilityLabel("\(SchedulePresentation.modeName(block.mode)), \(block.timeLabel), \(block.dayLabel)")
            .accessibilityValue(block.enabled ? "Enabled" : "Disabled")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { select() }
            .accessibilityAction(named: Text("Edit mode and days")) { edit() }
            .accessibilityIdentifier("schedule-edit-\(block.id)-day-\(occurrenceDay)")
    }

    private func resizeHandle(_ edge: ScheduleCalendarEdit) -> some View {
        Circle().fill(.white).frame(width: 12, height: 12)
            .overlay(Circle().stroke(.blue, lineWidth: 2))
            .frame(width: 44, height: 44).contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0, coordinateSpace: .named("schedule-grid"))
                .updating($held) { _, state, _ in state = true }
                .onChanged { changed(edge, $0) }.onEnded { _ in ended() })
            .accessibilityLabel(edge == .start ? "Change start time" : "Change end time")
            .accessibilityIdentifier("schedule-resize-\(edge.rawValue)-\(block.id)-day-\(occurrenceDay)")
    }
}

private struct ScheduleEmptyCalendarCell: View {
    let day: Int
    let hour: Int
    let hourHeight: CGFloat
    let tap: (Int) -> Void
    let began: () -> Void
    let changed: (DragGesture.Value) -> Void
    let ended: () -> Void
    let cancelled: () -> Void
    @GestureState private var held = false

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
        .simultaneousGesture(SpatialTapGesture().onEnded { value in
            let quarter = max(0, min(3, Int(value.location.y / hourHeight * 4)))
            tap(hour * 60 + quarter * 15)
        })
        .simultaneousGesture(LongPressGesture(minimumDuration: 0.35)
            .sequenced(before: DragGesture(minimumDistance: 1, coordinateSpace: .named("schedule-grid")))
            .updating($held) { _, state, _ in state = true }
            .onChanged { value in
                switch value {
                case .first(true), .second(true, nil): began()
                case .second(true, let drag?): changed(drag)
                default: break
                }
            }
            .onEnded { value in if case .second(true, .some) = value { ended() } else { cancelled() } })
        .onChange(of: held) { _, active in if !active { cancelled() } }
        .accessibilityElement()
        .accessibilityLabel("Add schedule at \(SchedulePresentation.clock(hour * 60))")
        .accessibilityAddTraits(.isButton).accessibilityAction { tap(hour * 60) }
        .accessibilityIdentifier("schedule-add-hour-\(hour)-day-\(day)")
    }
}

private struct ScheduleCalendarBlockContent: View {
    let block: TickerScheduleBlock
    let pending: Bool
    let selected: Bool

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
    private var compactTime: String {
        "\(shortClock(block.start_minute))–\(shortClock(block.end_minute))"
    }
    private var compact: Bool { selected && block.end_minute - block.start_minute < 45 }
    private func shortClock(_ minute: Int) -> String {
        let hour = (minute / 60) % 24
        let display = hour % 12 == 0 ? 12 : hour % 12
        let fraction = minute % 60 == 0 ? "" : String(format: ":%02d", minute % 60)
        return "\(display)\(fraction)\(hour >= 12 ? "PM" : "AM")"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(SchedulePresentation.modeName(block.mode)).font((compact ? Font.caption2 : Font.caption).weight(.semibold))
                .lineLimit(compact ? 1 : 3)
            if !compact {
                Text(compactTime).font(.caption2).lineLimit(2)
                if !block.enabled { Text("Off").font(.caption2).foregroundStyle(.secondary) }
            }
            if pending { ProgressView().controlSize(.mini) }
            Spacer(minLength: 0)
        }
        .foregroundStyle(.white).padding(.horizontal, 6).padding(.vertical, compact ? 1 : 6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(color.opacity(block.enabled ? 0.3 : 0.08), in: RoundedRectangle(cornerRadius: 6))
        .overlay(alignment: .leading) { RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 3) }
        .overlay {
            RoundedRectangle(cornerRadius: 6).strokeBorder(selected ? Color.white : color.opacity(0.65),
                style: StrokeStyle(lineWidth: selected ? 2 : 1, dash: block.enabled ? [] : [4, 3]))
        }
        .opacity(block.enabled ? 1 : 0.55)
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
         timeZone: TimeZone, initialDays: [Int]?, initialStart: Int, initialEnd: Int?,
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
        _endDate = State(initialValue: SchedulePresentation.timeDate(minute: block?.end_minute ?? initialEnd ?? min(initialStart + 60, 1440), timeZone: timeZone))
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
