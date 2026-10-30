import Foundation
import SwiftUI

/// The weekly schedule of one ticker as a calendar. A tap on a block edits it. A tap on empty space adds a block.
struct ScheduleView: View {
    @Environment(TickerStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let ticker: TickerRecord

    @State private var schedule: Schedule?
    @State private var scope: ScheduleCalendarScope = .weekdays
    @State private var selectedDay = 0
    @State private var dayCount = 3
    @State private var blockEditor: BlockSelection?
    @State private var conditionEditor: ConditionSelection?
    @State private var updatingOverride = false
    @State private var loading = false
    @State private var errorMessage: String?
    @State private var loadRevision = 0

    @ScaledMetric(relativeTo: .body) private var hourHeight: CGFloat = 72

    private var timeZone: TimeZone { schedule?.timeZone ?? .current }
    private var columns: [ScheduleCalendarColumn] { scope.columns(start: selectedDay, count: dayCount) }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                header
                if schedule != nil {
                    calendar
                    controls
                } else if loading {
                    Spacer()
                    ProgressView("Loading your schedule…")
                    Spacer()
                } else {
                    ContentUnavailableView {
                        Label("Schedule unavailable", systemImage: "calendar.badge.exclamationmark")
                    } description: {
                        Text("Check the connection and try again.")
                    } actions: {
                        Button("Try again") { Task { await load() } }
                    }
                }
                if let errorMessage {
                    Text(errorMessage).font(.footnote).foregroundStyle(.red).padding(12).accessibilityIdentifier("schedule-error")
                }
            }
            .background(background)
            .navigationTitle("Schedule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .primaryAction) {
                    Button { add() } label: { Image(systemName: "plus") }
                        .accessibilityLabel("Add schedule").accessibilityIdentifier("schedule-add")
                        .disabled(schedule == nil || loading)
                }
            }
            .sheet(item: $blockEditor) { selection in
                ScheduleBlockEditor(tickerID: ticker.id, block: selection.block, modes: ticker.schedulableModes, timeZone: timeZone,
                                    days: selection.days, start: selection.start, onSaved: changed)
            }
            .sheet(item: $conditionEditor) { selection in
                ScheduleConditionEditor(tickerID: ticker.id, condition: selection.condition, liveGames: schedule?.liveGames ?? 0, onSaved: changed)
            }
            .task { await load() }
        }
        .preferredColorScheme(.dark).tint(.blue).presentationDetents([.large])
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(ticker.name).font(.headline)
                    Text("Repeating week · \(schedule?.timezone.replacingOccurrences(of: "_", with: " ") ?? "Loading…")")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                if loading { ProgressView().controlSize(.small) }
            }
            if schedule?.effective.override == true {
                Label("Paused until the next scheduled change", systemImage: "pause.circle").font(.caption).foregroundStyle(.orange)
            }
            Picker("Schedule days", selection: $scope) {
                ForEach(ScheduleCalendarScope.allCases, id: \.self) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented).accessibilityIdentifier("schedule-scope-picker")
            if scope == .days { dayControls }
            HStack(spacing: 0) {
                Text(timeZone.abbreviation() ?? "Time").font(.caption2).foregroundStyle(.secondary).frame(width: 36)
                ForEach(columns) { column in
                    Text(columns.count == 1 ? column.title : String(column.title.prefix(3)))
                        .font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity)
                }
            }
        }
        .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 14)
    }

    private var dayControls: some View {
        VStack(spacing: 8) {
            HStack {
                Picker("Calendar view", selection: $dayCount) {
                    Text("Day").tag(1)
                    Text("3 days").tag(3)
                }
                .pickerStyle(.segmented).frame(width: 150).accessibilityIdentifier("schedule-view-picker")
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
                    HStack(spacing: 6) { ForEach(0..<7, id: \.self) { dayButton($0) } }
                }
            }
        }
    }

    private func dayButton(_ day: Int) -> some View {
        let selected = selectedDay == day
        return Button { selectedDay = day } label: {
            Text(String(SchedulePresentation.weekdays[day].prefix(3))).font(.subheadline.weight(.semibold))
                .frame(minWidth: 44, minHeight: 44)
                .background(selected ? Color.blue : Color.white.opacity(0.06), in: Capsule())
                .foregroundStyle(selected ? Color.white : Color.secondary)
        }
        .buttonStyle(.plain).accessibilityLabel(SchedulePresentation.weekdays[day])
        .accessibilityValue(selected ? "Selected" : "Not selected")
        .accessibilityIdentifier("schedule-filter-\(day)")
    }

    private var calendar: some View {
        ScrollViewReader { proxy in
            ScrollView {
                grid
                Text("Tap a block to change its times, mode, or repeat days. Tap empty space to add one.")
                    .font(.footnote).foregroundStyle(.secondary).padding(.horizontal, 20)
                Text("Outside these blocks, your ticker uses its usual settings.")
                    .font(.footnote).foregroundStyle(.secondary).padding(20)
            }
            .refreshable { await load() }
            .onAppear { proxy.scrollTo("schedule-hour-7", anchor: .top) }
            .onChange(of: selectedDay) { _, _ in proxy.scrollTo("schedule-hour-7", anchor: .top) }
            .onChange(of: scope) { _, _ in proxy.scrollTo("schedule-hour-7", anchor: .top) }
        }
    }

    private var grid: some View {
        GeometryReader { geometry in
            ZStack(alignment: .topLeading) {
                VStack(spacing: 0) {
                    ForEach(0..<24, id: \.self) { hour in hourRow(hour).id("schedule-hour-\(hour)") }
                }
                ForEach(Array(columns.enumerated()), id: \.element.id) { index, column in
                    ForEach(SchedulePresentation.calendarPlacements(column.blocks(schedule?.blocks ?? []),
                                                                    minimumMinutes: scope == .days ? 45 : 60)) { placement in
                        block(placement, column: column, index: index, width: geometry.size.width)
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
                    EmptyHourCell(column: column, hour: hour, hourHeight: hourHeight) { add(start: $0, days: column.days) }
                }
            }
        }
        .frame(height: hourHeight)
    }

    private func block(_ placement: ScheduleCalendarPlacement, column: ScheduleCalendarColumn, index: Int, width: CGFloat) -> some View {
        let block = placement.block
        let dayWidth = max(1, width - 56) / CGFloat(columns.count)
        let laneWidth = dayWidth / CGFloat(placement.columns)
        let height = CGFloat(placement.visualEnd - block.startMinute) / 60 * hourHeight
        return Button { blockEditor = BlockSelection(block: block, days: block.daysOfWeek, start: block.startMinute) } label: {
            BlockContent(block: block, showRepeat: scope != .days).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .frame(width: max(1, laneWidth - 4), height: max(1, height - 3), alignment: .topLeading)
        .offset(x: 56 + CGFloat(index) * dayWidth + CGFloat(placement.column) * laneWidth,
                y: CGFloat(block.startMinute) / 60 * hourHeight)
        .accessibilityLabel("\(SchedulePresentation.modeName(block.mode)), \(block.timeLabel), \(block.dayLabel)")
        .accessibilityValue(block.enabled ? "Enabled" : "Disabled")
        .accessibilityHint("Edit schedule")
        .accessibilityIdentifier("schedule-edit-\(block.id)-\(column.id)")
    }

    private var controls: some View {
        HStack {
            liveRule
            Spacer(minLength: 0)
            if schedule?.effective.hasEnabledRules == true {
                let paused = schedule?.effective.override == true
                Button { Task { await setOverride(!paused) } } label: {
                    Label(paused ? "Resume schedule" : "Pause schedule", systemImage: paused ? "play.circle" : "pause.circle")
                        .font(.subheadline.weight(.medium)).frame(minHeight: 44)
                }
                .tint(.orange).disabled(updatingOverride).accessibilityIdentifier("schedule-override")
            }
        }
        .padding(.horizontal, 20).padding(.vertical, 5).background(.ultraThinMaterial)
    }

    @ViewBuilder private var liveRule: some View {
        let label = Label("Live sports rule", systemImage: "bolt.fill").font(.subheadline.weight(.medium)).frame(minHeight: 44)
        if let conditions = schedule?.conditions, conditions.count > 1 {
            Menu {
                ForEach(conditions) { condition in
                    Button(condition.label) { conditionEditor = ConditionSelection(condition: condition) }
                }
            } label: { label }
            .accessibilityIdentifier("schedule-rules")
        } else {
            Button { conditionEditor = ConditionSelection(condition: schedule?.conditions.first) } label: { label }
                .accessibilityIdentifier("schedule-rules")
        }
    }

    private var background: some View {
        LinearGradient(colors: [Color(red: 0.14, green: 0.19, blue: 0.25), Color(red: 0.04, green: 0.06, blue: 0.09)],
                       startPoint: .top, endPoint: .bottom)
            .ignoresSafeArea()
    }

    private func add(start: Int = 480, days: [Int]? = nil) {
        blockEditor = BlockSelection(block: nil, days: days ?? columns[0].days, start: start)
    }

    private func changed() {
        store.scheduleChanged()
        Task { await load() }
    }

    /// Read the schedule. Only the latest read applies. The first read opens the calendar on today.
    private func load() async {
        loadRevision += 1
        let revision = loadRevision
        loading = true
        let result: Result<Schedule, Error>
        do { result = .success(try await store.loadSchedule(ticker.id)) } catch { result = .failure(error) }
        guard revision == loadRevision else { return }
        loading = false
        switch result {
        case .success(let value):
            if schedule == nil, (0...6).contains(value.effective.dayOfWeek) { selectedDay = value.effective.dayOfWeek }
            schedule = value
            errorMessage = nil
        case .failure(let error):
            errorMessage = error.localizedDescription
        }
    }

    private func setOverride(_ enabled: Bool) async {
        updatingOverride = true
        defer { updatingOverride = false }
        do {
            try await store.setScheduleOverride(ticker.id, enabled: enabled)
            changed()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct BlockSelection: Identifiable {
    let id = UUID()
    let block: ScheduleBlock?
    let days: [Int]
    let start: Int
}

private struct ConditionSelection: Identifiable {
    let id = UUID()
    let condition: ScheduleCondition?
}

private struct EmptyHourCell: View {
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

private struct BlockContent: View {
    let block: ScheduleBlock
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

    /// A short time such as "8AM" or "6:30PM".
    private func shortClock(_ minute: Int) -> String {
        let hour = (minute / 60) % 24
        let display = hour % 12 == 0 ? 12 : hour % 12
        let fraction = minute % 60 == 0 ? "" : String(format: ":%02d", minute % 60)
        return "\(display)\(fraction)\(hour >= 12 ? "PM" : "AM")"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(SchedulePresentation.modeName(block.mode)).font(.caption.weight(.semibold)).lineLimit(3)
            Text("\(shortClock(block.startMinute))–\(shortClock(block.endMinute))").font(.caption2).lineLimit(2)
            if showRepeat { Text(block.dayLabel).font(.caption2).foregroundStyle(.white.opacity(0.8)) }
            if !block.enabled { Text("Off").font(.caption2).foregroundStyle(.secondary) }
            Spacer(minLength: 0)
        }
        .foregroundStyle(.white).padding(.horizontal, 6).padding(.vertical, 6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(color.opacity(block.enabled ? 0.3 : 0.08), in: RoundedRectangle(cornerRadius: 6))
        .overlay(alignment: .leading) { RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 3) }
        .overlay {
            RoundedRectangle(cornerRadius: 6).strokeBorder(color.opacity(0.65), style: StrokeStyle(lineWidth: 1, dash: block.enabled ? [] : [4, 3]))
        }
        .opacity(block.enabled ? 1 : 0.55)
    }
}
