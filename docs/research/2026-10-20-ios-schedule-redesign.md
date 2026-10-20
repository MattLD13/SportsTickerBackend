# iOS schedule editor

Date: 2026-10-20

## Current design

The user selected colored calendar blocks with tap editing.
Weekdays is the default view. Weekends and By day remain visible as top-level options.
By day provides one-day and three-day views.
Tapping a block opens one form for its times, mode, repeat days, and enabled state.
The form provides deletion with confirmation.
Tapping empty space selects a quarter-hour start time.
New blocks in Weekdays select Monday through Friday. New blocks in Weekends select Saturday and Sunday.
The native time pickers use 15-minute increments.

Grouped views display each stored block once.
A block that applies to only Monday retains its Mon label and its original repeat days.
The editor does not broaden a partial schedule when the user opens it from a group.
Overlapping visible blocks use separate columns.
Group labels reserve enough height for the actual repeat days without changing stored times.

The general live sports rule remains separate from time blocks.
Its default comparison is More than. The user can also select At least.
The rule uses the existing V2 sports condition and runs while Sports mode is active.
Pinned games retain priority.

The Home screen places a small Override or Resume button beside the Connected ticker menu.
It uses the existing blue accent and native capsule style without adding another card.
Override pauses the schedule until the server's next scheduled change. Resume restores automatic scheduling immediately.
Its accessibility hint gives the server's resume time in the ticker's time zone.
Failed requests retain the confirmed state and show a native error alert.

## Apple controls

The app uses native navigation, forms, segmented controls, menus, alerts, switches, and time pickers.
UIKit UIDatePicker supplies the compact time control and its quarter-hour interval.
The ticker calendar layout is custom SwiftUI.
The app keeps recurring ticker rules in the existing server API.
It does not add events to the user's Calendar database.

References:

- [Apple UIDatePicker](https://developer.apple.com/documentation/uikit/uidatepicker)
- [Apple EventKit UI](https://developer.apple.com/documentation/eventkitui)
- [Apple Health recurring schedules](https://support.apple.com/guide/iphone/edit-sleep-schedules-iph304a683a0/ios)

## Behavior owners

`ScheduleCalendarScope` owns the visible weekday groups.
`ScheduleCalendarColumn` selects the matching stored blocks and quarter-hour placement.
`SchedulePresentation` owns labels, local time conversion, ordering, and calendar placement.
`TickerScheduleView` owns editor presentation and refresh ordering.
`ScheduleBlockEditor` owns the form, save, cancellation, and confirmed deletion.
`TickerViewModel` sends the existing authenticated V2 requests.
Its published schedule status comes from the explicit display metadata.
The Home control uses the existing request gate to reject replaced ticker, server, and authorization sessions.
It invalidates earlier display reads before refreshing a successful override.
The server owns persistence, overlap rejection, effective settings, and override expiration.

The change removes drag movement, resize handles, gesture previews, gesture state, and their superseded tests.
It removes the selection toolbar and block context menu.
Each block now has one native button action that opens its editor.

## Input and output evidence

The simulator uses production views and TickerViewModel with an injected in-memory transport.
Its credentials do not access the real keychain. Its requests do not reach a live server.
The preview compiles only in Debug.

A Weekdays save creates one block with days `[0, 1, 2, 3, 4]`.
A Weekends save creates one block with days `[5, 6]`.
A Monday-only weather block remains Monday-only after the user opens its grouped editor.
The sports block ends at minute `1440` and displays Midnight when reopened.
Disabling a block retains its identifier. Cancelling an editor does not write a block.
An overlap response leaves the editor open and shows the error.
Cancelling deletion retains the editor. Confirming deletion removes the saved block.
The general rule saves More than 6 games live through the existing condition endpoint.
The Home check overrides and resumes the schedule through the production request path.
The failed-override check keeps Schedule on visible and allows another attempt.

## Reproduce the screen checks

Use a Mac with Xcode and XcodeGen.

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

The package checks cover groups, partial schedules, labels, overlap layout, intervals, and time zone conversion.
The screen checks cover grouped creation, tap editing, cancellation, deletion, sports filters, connection recovery, live rules, and manual control.

## Validation

All 43 package tests passed in Debug and Release.
All 13 calendar interaction checks passed. Both Home override checks passed.
Focused checks verified deletion confirmation, the default Weekdays selection, partial-day preservation, and More than 6 games live.
The production Release simulator build passed.
The signed iPhone Release build passed strict code-signature verification.
The repository suite passed 1,088 tests, with ten skips.
The critical suite passed 738 tests, with ten skips and 350 deselected tests.
The combined simulator run passed all 15 interaction checks.
After the Home control moved beside Connected, its position, size, pause, resume, and failure checks passed again.
