# iOS schedule redesign

Date: 2026-10-20

## Design references

[Apple Health](https://support.apple.com/guide/iphone/edit-sleep-schedules-iph304a683a0/ios) groups recurring schedules by days and times.
[Fantastical](https://flexibits.com/fantastical-ios/help/editing-events-and-tasks) provides direct editing.
[Google Calendar](https://support.google.com/calendar/answer/72143?co=GENIE.Platform%3DiOS&hl=en) supports creating an event from an empty time.

The user selected calendar blocks instead of the first list design.
The controller positions colored mode blocks against a time grid with quarter-hour lines.
Each block shows its mode, time range, and enabled state.
The default view shows three recurring weekdays. The Day view shows one weekday.
Navigation arrows move the visible range. Day buttons select a weekday in the Day view.
Tapping empty space selects its quarter-hour start time.
Holding and dragging empty space selects a new time range.
Holding a block moves its time and repeating day pattern.
Selecting a block shows separate start and end resize handles.
All new placement and gesture changes use 15-minute increments.
The native time pickers also use 15-minute increments.
The editor groups mode, repeat days, start time, and end time.
Presets select every day, weekdays, or weekends.
The existing live sports rule and temporary manual control remain available.

## Behavior owners

`TickerScheduleView` owns selection, editor presentation, and mutation feedback.
`SchedulePresentation` owns labels, local time conversion, day filtering, and calendar placement.
`ScheduleCalendarInteraction` owns quarter-hour snapping, move bounds, resize bounds, and drawing ranges.
`TickerViewModel` sends the existing authenticated V2 schedule requests.
The server still owns persistence, overlap rejection, schedule evaluation, and override expiration.

The redesign replaces the old timeline gesture handling and its interaction fixture.
The replacement editor has explicit save and cancel actions.
It preserves existing mode, days, enabled state, and midnight end times.
Every editor presentation has its own identity and captures the selected schedule.
This prevents a reused editor from loading default values for an existing schedule.
Deletion requires confirmation and captures the schedule before the alert closes.
The gesture path replaces the former tap-only calendar block.
A recognized hold locks scrolling before block movement starts.
An ordinary swipe continues to scroll the calendar.
The former block context menu intercepted the hold gesture.
The selected block now has an explicit actions menu for disabling and deletion.
The Edit mode and days button opens its form.
The display previews a gesture without changing the saved schedule.
The app saves one V2 block update after release.
Repeated blocks require confirmation before the app changes all repeat days.
A horizontal move shifts the complete repeat pattern and preserves its number of days.
The confirmation shows the resulting days and times.
Rejected saves restore the saved block and show the server error.

## Input and output evidence

The preview uses the production schedule views and `TickerViewModel`.
Its injected transport handles V2 requests in memory and never contacts a live server.
Its injected credential store never reads the real keychain.
The preview compiles only in Debug builds.

The sports fixture contains weekdays, start minute `1080`, and end minute `1440`.
Its editor must show `6:00 PM – Midnight` and leave weekends unselected.
Disabling and saving that block must retain its identifier and return `enabled: false`.
Creating a weekend schedule must send `[5, 6]` through the production request path.
An overlap response must leave the editor open and show the server's error.
Deleting a schedule requires explicit confirmation.
Cancelling an editor must not create a schedule.
Moving the Monday weather block to Tuesday sends day `[1]`, start minute `465`, and end minute `525`.
The saved frame shows Tuesday, `7:45 AM – 8:45 AM`.
The two resize gestures save `7:30 AM – 8:30 AM` without changing the block identifier or mode.
Moving weather into the stock block returns an overlap error and leaves the original saved times visible.
Drawing from `10:00 AM` to `11:30 AM` opens a form with that range.
Unselected short blocks have a minimum visible height. Their stored times do not change.
Selecting a short block exposes handles at its actual quarter-hour bounds.
Visually overlapping blocks use separate columns so adjacent short schedules remain available.

## Reproduce the screen checks

Use a Mac with Xcode and XcodeGen.
Generate the isolated preview project outside the checkout:

```sh
xcodegen generate --spec TickerControlApp/schedule-ui-tests.yml --project /tmp/ticker-schedule-ui
xcodebuild test \
  -project /tmp/ticker-schedule-ui/ScheduleUI.xcodeproj \
  -scheme ScheduleUI \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  -collect-test-diagnostics never \
  -parallel-testing-enabled NO \
  INFOPLIST_FILE="$PWD/TickerControlApp/TickerControl-Info.plist" \
  CODE_SIGNING_ALLOWED=NO
```

The screen checks cover day filters, creation, presets, cancellation, empty selection, editing, deletion, server errors, live rules, and manual control.
The package checks cover labels, supported mode names, ordering, interval validation, and time zone conversion.
The phone remains disconnected during this work. The simulator supplies the screenshots and recordings.

## Validation results

All 43 Swift package tests passed in Debug and Release.
All 17 simulator interaction tests passed on iPhone 17 Pro Max with iOS 27.
The production Release simulator build passed.
After the day-column boundary guard changed, the package tests and cross-day movement check passed again.
The repository suite passed 1,088 tests, with ten skips.
The critical suite passed 738 tests, with ten skips and 350 deselected tests.

The checks found an editor state reuse error during development.
The final editor identity fix preserves the selected block's values.
The checks also required an explicit delete alert and a direct tap on the native switch control.
The final assertions still verify cancellation, enabled state, saved times, and persisted identifiers.
The direct editing checks cover movement, day changes, resizing, drawing, repeat confirmation, and rejected saves.
The local evidence retains the initial failed runs and final passing results.
