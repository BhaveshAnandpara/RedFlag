# UI screens build plan

Design: `docs/superpowers/specs/2026-10-19-ui-screens-design.md` (approved 2026-10-19).
Method: the `design-taste-frontend` skill (`.agents/skills/design-taste-frontend`), its page run for the home page and its app-screen run (`references/app-screens.md`) for `/scan` and `/results`, with one shared palette and typeface. Each screen is a standalone HTML file rendered to PNG. Nothing in `frontend/` changes.

Tools checked: Node v24 (the skill needs 22+), Chrome and Edge installed.

Output layout:
- `design/screens/*.html`: one file per screen, plus `design/screens/shared.css` (tokens, header, footer, badges).
- `design/screens/png/`: exported images, `<screen>-desktop.png` (1440 wide) and `<screen>-phone.png` (375 wide), full page.
- `design/screens/index.html`: a contact sheet linking every screen and image.
- `.taste-skill/`: the skill's working files, added to `.gitignore`.

Every phase ends with the skill's inspector (`inspect.mjs`, or `inspect.mjs --app`) passing and screenshots at three widths looked at and fixed. Commit after each phase only when the owner asks.

## Phase 1: Shared direction

1. Inventory the subject in notes (the skill's step 1): the name and the referee's flag, the foul and the whistle, the planted secret code, the tool log, the OWASP list, the weak and hardened bots, the "not a guarantee" line, the real incidents.
2. Write the home page argument, one claim and its proof per section, in the approved order.
3. Deal the page direction with `draw.mjs --options 3`, sections in the approved order. Choose the one that can carry "a linesman's flag raised on the exact failing line". Map the dealt palette roles onto **black and red** (owner's constraint); redraw the palette only if it cannot be mapped, and record it.
4. Write the idea sentence: *On this page, the referee's raised flag on a foul becomes [the device the direction calls for].* Pass the competitor test.
5. Deal the app style with `draw.mjs --app --keep palette,type` for `/scan` and `/results`.
6. Build `shared.css`: colour tokens (black ground, brand and fail red as one red, green, yellow and grey status tones readable on black at WCAG AA), type scale, the placeholder wordmark with its flag mark, header (wordmark, How it works, Results, Run full scan) and footer (same links, GitHub, the "not a guarantee" line).

Check: status tone contrast measured on black; the header and footer render at 375 and 1440 without sideways scroll.

## Phase 2: Home page

7. Hero: black and red, the "Sound on" toggle, **Run full scan**. Headline within the wording rules.
8. The foul scene as a strip of key frames (typing, reply arriving, flag up with the failing line marked), using one real failure from scan #4 with its real message, reply and tool log.
9. **Run full scan** below the scene.
10. Why Redflag exists: the owner's line, then three incident cards. Before writing them, check each fact (Chevrolet $1 car, December 2023; Moffatt v. Air Canada, February 2024; DPD, January 2024) against a primary or major news source and record the links in the HTML.
11. How we test your AI agent: the three parts as plain features (owner's decision, no status tags).
12. Dashboard showcase: a cropped piece of the Phase 4 weak results screen, built as a real app fragment (shares its CSS), not a screenshot.
13. Repeat **Run full scan**, then the footer.

Check: `inspect.mjs` passes; screenshots at three widths reviewed against the skill's juror rubric and fixed; no "safe", "secure" or "ready" said of a bot.

## Phase 3: `/scan`

14. `scan-before.html`: bot picker (weak and hardened, one line each on defenses), the chat area empty with a short intro from the bot, disabled message box, **Run scan**.
15. `scan-during.html`: "Scan running: 7 of 16", seven finished exchanges from scan #4 in order with quiet badges, the eighth attack mid-typing and typing dots from the bot; a small inset showing the "No new result yet…" note.
16. `scan-limit.html`: the weak bot already scanned: the limit note and a link to its result; the hardened bot still available. A small inset for the busy state ("Another scan is running. You're next, about 40 seconds.").

Check: `inspect.mjs --app` passes; three widths reviewed; every badge shows its word.

## Phase 4: `/results/<id>`

17. `results-weak.html` from scan #4: the verdict in counts ("5 of 13 attacks got through. 4 were critical." and "3 of 3 normal requests worked"), the 16-flag row, meta line, closing line, Download report and Copy link; Fix these first (five cards, critical first, one expanded with message, reply, tool log with the harmful call highlighted, the Plain rules and AI judge blocks with the judge marked NOT RUN); the OWASP coverage (five tested, five not tested); the all-tests table with filters; Next step "Now scan the hardened bot"; collapsed scan details. The attack success rate with its 95% range and small-sample note as one line.
18. `results-hardened.html` from scan #5: 16 of 16 passed, the verdict banner not plain green because five risks were not tested, the untested risks and the closing line prominent, Next step as the weak-versus-hardened comparison (same models answered both).

All counts are computed from `frontend/src/data/sample-scans.json`, not typed by hand: a small script in `design/screens/` reads the file and writes the numbers into the HTML, or the HTML loads the JSON directly (builder's choice).

Check: `inspect.mjs --app` passes; the counts on screen match the file; the wording rules hold, including the hardened scan never reading as safe.

## Phase 5: Review and export

19. Run `design:accessibility-review` and `design:ux-copy` over the five screens; fix what they find.
20. Export every screen at 1440 and 375 wide, full page, to `design/screens/png/`.
21. Build `design/screens/index.html`, the contact sheet.
22. Hand the images to the owner for review.

## Risks to watch

- **Red overload:** a black and red site where red also means fail. Watch that results screens do not look alarming when nothing failed (the hardened scan).
- **Static motion:** the foul scene has to read as a sequence in a still image; if the key frames are unclear, add frame numbers and one-line captions.
- **Invented numbers:** anything on screen that is not in the saved scans or a cited source is a defect.
- **Feature claims:** the "How we test" section describes M6 and M7 as live by the owner's decision; the owner must build them or edit the page before it ships.
