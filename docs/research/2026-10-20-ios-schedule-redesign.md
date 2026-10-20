# iOS schedule redesign

Date: 2026-10-20

## Design references

[Apple Health](https://support.apple.com/guide/iphone/edit-sleep-schedules-iph304a683a0/ios) groups recurring schedules by days and times.
[Fantastical](https://flexibits.com/fantastical-ios/help/editing-events-and-tasks) provides direct editing.
[Google Calendar](https://support.google.com/calendar/answer/72143?co=GENIE.Platform%3DiOS&hl=en) supports creating an event from an empty time.

The user selected calendar blocks instead of the first list design.
The controller now positions colored mode blocks against an hourly time grid.
Each block shows its mode, time range, and enabled state.
Day buttons select the recurring weekday without changing stored schedules.
Tapping an empty hour opens an editor with that start time.
The editor groups mode, repeat days, start time, and end time.
Presets select every day, weekdays, or weekends.
The existing live sports rule and temporary manual control remain available.

## Behavior owners

`TickerScheduleView` owns selection, editor presentation, and mutation feedback.
`SchedulePresentation` owns labels, local time conversion, day filtering, and calendar placement.
`TickerViewModel` sends the existing authenticated V2 schedule requests.
The server still owns persistence, overlap rejection, schedule evaluation, and override expiration.

The redesign replaces the old timeline gesture handling and its interaction fixture.
The replacement editor has explicit save and cancel actions.
It preserves existing mode, days, enabled state, and midnight end times.
Every editor presentation has its own identity and captures the selected schedule.
This prevents a reused editor from loading default values for an existing schedule.
Deletion requires confirmation and captures the schedule before the alert closes.

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
Short blocks have a minimum visible height. Their stored times do not change.
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

All 39 Swift package tests passed in Debug and Release.
All nine simulator interaction tests passed on iPhone 17 Pro Max with iOS 27.
The production Release simulator build passed.
The repository suite passed 1,088 tests, with ten skips.
The critical suite passed 738 tests, with ten skips and 350 deselected tests.

The checks found an editor state reuse error during development.
The final editor identity fix preserves the selected block's values.
The checks also required an explicit delete alert and a direct tap on the native switch control.
The final assertions still verify cancellation, enabled state, saved times, and persisted identifiers.
The local evidence retains the initial failed runs and final passing results.
