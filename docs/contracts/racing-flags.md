# Racing cards and race-control signals

## Owners

`ticker/shared/sports_display.py` owns signal identity, meaning, scope, and flag patterns.
`ticker/server/projections/racing_display.py` owns class cards and compact Mini data.
Provider adapters own current source reads. Renderers read explicit display facts without I/O.

The supported series are F1, IndyCar, NASCAR Cup, WEC, and IMSA WeatherTech.
Nürburgring 24h is not a supported series.

## Official signal audit

The audit uses these primary sources:

- [FIA Appendix H 2026, sections 2.5.4 and 2.5.5](https://www.fia.com/system/files/documents/appendix_h_2026_published_12032026.pdf).
- [F1 flag guide](https://www.formula1.com/en/latest/article/the-beginners-guide-to-formula-1-flags.T5DqOqbWI6S4Va8Y5yMld).
- [IndyCar 2026 rulebook, section 7.2](https://epaddock.indycar.com/docs/default-source/rules-regulations-and-policies/2026-indycar-rulebook.pdf).
- [NASCAR Cup team flag guide](https://www.hendrickmotorsports.com/news/2026/january/12/nascar-flags-and-their-meanings-what-each-flag-waved-in-a-race-represents).
- [NASCAR timing API specification](https://feed.nascar.com/swagger/ui/index).
- [NASCAR 2026 stage-break procedure](https://www.nascar.com/news-media/2026/08/06/nascar-to-implement-new-stage-break-procedure-beginning-at-iowa-speedway/).
- [IMSA 2026 Sporting Regulations, article 27 and article 49](https://www.imsa.com/wp-content/uploads/sites/32/2026/06/17/2026-IMSA-SPORTING-REGULATIONS-and-SSR-IWSC-Blackline-061726.pdf).
- [WEC 2026 race-control briefing](https://fiawec.alkamelsystems.com/Results_NoticeBoard/14_2026/01_6%20Hours%20of%20Imola/007_Doc%207%20-%20Drivers%27%20and%20Team%20Managers%27%20Briefing%20Notes.pdf).
- [Le Mans 2026 regulations, slow-zone procedure](https://fiawec.alkamelsystems.com/Results_NoticeBoard/14_2026/committee/00_Regulations/2026%20-%20Le%20Mans%20-%20Supplementary%20Regulation%20V2.pdf).

| Signal | Series or meaning distinction | Display |
|---|---|---|
| Green | All five series. Racing starts, resumes, or clears a hazard. | Green flag. |
| Yellow | All five series. Local danger and caution retain their reported scope. | Yellow flag. |
| Double yellow | FIA danger signal. IMSA also uses double yellow for full-course caution. | Two yellow bands. |
| Red | All five series. Activity stops. | Red flag and `RED`. |
| Chequered | All five series. Session or race ends. | Black and white checks. |
| White | FIA marshal signal: slow vehicle. American starter signal: last lap. | White flag with scope-specific text. |
| Plain blue | F1, IndyCar, WEC, and IMSA: approaching car. NASCAR road courses: obstruction ahead. | Plain blue flag. |
| Blue with yellow stripe | NASCAR passing advisory. IMSA permits the stripe. | Blue flag with yellow diagonal. |
| Black | FIA disqualification. American series use a pits instruction or penalty. | Black flag with a visible border. |
| Black with white cross | IndyCar and NASCAR: the car is no longer scored. | White cross on black. |
| Black and white diagonal | FIA and IMSA driving warning. | Diagonally divided flag. |
| Black with orange disc | FIA and IMSA mechanical concern. | Orange disc on black. |
| Yellow with red stripes | Reduced grip, liquid, or debris. All five rule systems describe the surface warning. | Alternating yellow and red stripes. |
| White with red cross | IndyCar safety vehicles or personnel on track. | Red cross on white. |
| Red with yellow cross | NASCAR pit entry closed. Some published descriptions call this a stripe. | Cross or diagonal variant, as reported. |
| Red and black together | NASCAR practice or qualifying ends. IMSA also uses the combination to stop cars beside the track. | Split red and black, with series-specific text. |
| Two crossed chequers | NASCAR optional halfway signal. | Crossed checks and `HALF`. |
| Chequers at a stage end | NASCAR stage completion does not finish the whole race. | Checks and `STAGE`. |
| Green and white chequers | NASCAR stage completion. Keep this separate from the overtime procedure. | Green and white checks. |
| Green and white chequers with yellow | NASCAR's revised 2026 stage-break procedure. | Green and white checks beside yellow. |
| Green and yellow together | NASCAR counts laps while the field remains paced. | Split green and yellow. |
| Green and white together | IMSA permits a restart on the last lap. | Split green and white. |

Standing and waved indications remain separate metadata where the source identifies them.
An explicit waved indication pulses the flag icon. A standing indication remains steady.
Car numbers and sectors remain separate fields. A car penalty does not change the whole track to a penalty state.

## Boards and timing-feed states

| State | Meaning and handling |
|---|---|
| SC | Safety car. Keep the `SC` label distinct from VSC and yellow. |
| SC ending | Safety car withdrawal. Show amber and green. |
| VSC | Virtual safety car. Supported by F1 and WEC. |
| VSC ending | VSC withdrawal. Show amber and green with its own label. |
| FCY | Full-course yellow. Keep the `FCY` label. |
| SLOW ZONE | Local speed-controlled section. Preserve its sector when supplied. |
| NEXT SLOW | Advance notice of a slow zone. |
| Last lap | Explicit timing-feed last-lap state. Do not infer this from a lap counter. |
| Last lap with yellow, SC, or VSC | WEC combined timing states. Keep the caution condition. |
| Chequered with yellow, SC, or VSC | WEC combined finish states. Keep the caution condition after completion. |
| White with yellow or SC | WEC timing vocabulary. Preserve both reported indications. |
| Temporary chequered | WEC timing vocabulary. Show a chequered signal. |
| GWC | NASCAR overtime procedure. This is a procedure label, not a separate physical flag. |
| Code 60 | The Alkamel client supports `C60`. This does not establish normal use in IMSA WeatherTech. |
| National start flag | FIA Appendix H permits this general start signal. Show `START` without inventing a country's flag. |
| All-black or furled black | Recognized instruction and warning variants retain their own labels. |
| None | Upcoming or inactive session. Show a neutral indicator. |
| Unknown | Unrecognized or absent live source value. Show gray and `?`. Never use green. |

## Source limits

Display support does not mean every public timing feed supplies every physical flag.

- F1 uses the ESPN competition flag. Missing car-specific flags remain missing.
- IndyCar uses its dated Series I timing heartbeat and explicit car flag fields.
- NASCAR uses race-specific Cup timing. The documented numeric states are green, yellow, red, finish, stop, warm-up, and inactive.
- WEC selects the latest global flag by source timestamp. Car, class, and sector reports cannot replace the global flag.
- IMSA uses the current Alkamel `session_status.currentFlag`. Current messages are not parsed into invented flag events.

The WEC and Alkamel web-client vocabularies were inspected alongside recorded source responses.
Historical flag messages are not presented as active flags without an explicit active indication.
Missing driver penalties and local cautions are not inferred from weather, lap counts, or display text.

## Display contract

`data.racing_display.cards` contains one top-three card per class.
The original series payload keeps the full classification for the pinned Six carousel.

Each card contains race name, class identity, session, explicit state, status, signals, and rows.
Rows contain class position, overall position, car number, abbreviation, metric, compact metric, number style, and text colors.
Leading zeroes remain part of the car number.

Signals contain canonical code, original value, meaning, scope, car, sector, motion, colors, and physical pattern.
The Mini projection includes a prepared 5x5 RGB565 flag raster and a compact signal label.
Six renders the same pattern at 9x6 and 15x10.

Mini sports rotation includes both `content.sports` and `content.racing`.
Signal rotation uses a continuous presentation clock. Changing pages cannot repeatedly hide later signals.
Each Mini class card has a stable event-and-class ID. The retained JSON filter includes racing cards.
Compact racing cards retain shared lifecycle, status, situation, and competition-stage facts.
Numbers use verified number art, reference livery accents, or provider team colors. Missing color data uses readable white.
The color registry is season-specific. It identifies number-art colors separately from general livery accents.
Positions one, two, and three use gold, silver, and bronze. Time and gap colors remain unchanged.

## Validation

`tools/mini/racing_vectors.py` exports the Mini contract cases.
`tests/mini/mini_racing.cpp` checks the retained filter, class rotation, podium colors, and every signal raster at 64x32.
Python checks cover source aliases, white-flag meanings, signal scope, unknown values, and all three raster sizes.
Recorded Cup, WEC, IMSA, and F1 responses verify the data boundary independently of the synthetic flag cases.
