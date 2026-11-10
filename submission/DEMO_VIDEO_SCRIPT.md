# TESSERA demo video: script and shot list

Target length: 4:00 (the form sets no limit; keep to 4:00) at a calm 130 words a minute. Narration is about 520 words.
Slides come from the site deck. Each slide link opens on that slide: `https://alicia112233.github.io/SingHacks2026/slides.html#N`. Press F for full screen.
App: `https://singhacks-jb-wealth-intelligence.vercel.app` (use this short URL; the long `-facah2d66` one asks for a Vercel login).

## Before you record

- [ ] Browser at 100% zoom, window 1920×1080, bookmarks bar and extensions hidden, notifications off (Focus assist on).
- [ ] Open the app once and wait for "Loading current portfolio records" to finish before you start recording. The first load takes 5 to 10 seconds.
- [ ] Record the narration separately (phone or headset mic in a quiet room), then lay the screen takes under it. Redo single lines instead of whole takes.
- [ ] Record every screen take with the mouse moving slowly. Pause 1 second on each thing you point at.
- [ ] Recorder: Xbox Game Bar (`Win+Alt+R`) or OBS. Editor: Clipchamp (built into Windows 11).

## What to record (Claude does the edit)

The slides are already rendered, so you only record two things.

1. **Your voice, one file per shot.** Use Windows Sound Recorder or your phone. Name the files by shot number, `01` to `15`, plus `05b` for the Telegram shot (any audio format). Read the Narration column for that row, leave a second of silence before and after, and redo any file you stumble in.
2. **The app, as one continuous screen recording** covering shots 5 to 11 in order. Pause about 2 seconds on each shot, and don't worry about pace or mistakes; the cutting fixes both. You can split it into several files if that's easier. The take's own sound is not used.
3. **Your phone, for shot 5b.** Use the phone's own screen recorder while the Telegram alert arrives and you open it. Setting up the bot is in the next section.

Put everything in `video-edit/narration/` and `video-edit/takes/` (or anywhere, and say where). Claude then trims each take to its line, speeds up slow scrolling, cuts the chat wait, holds each slide for its line, cleans and levels the voice, and exports `video-edit/out/TESSERA_demo.mp4` at 1080p.

## Setting up the Telegram alert for shot 5b

The alert only runs on the local server; Vercel has no bot configured.

1. In Telegram, message **@BotFather**, send `/newbot`, and name it (for example "TESSERA Alerts"). It replies with a bot token.
2. Open your new bot and send it any message, such as "hi".
3. In a browser, open `https://api.telegram.org/bot<token>/getUpdates` with your token in place of `<token>`. Copy the number after `"chat":{"id":`. That is your chat ID.
4. Create `singhacks-jb-wealth-intelligence/.env.local` with two lines: `TELEGRAM_BOT_TOKEN=<token>` and `TELEGRAM_CHAT_ID=<chat id>`. The file is git-ignored; never commit it.
5. Start your phone's screen recorder, then run `python app.py --port 8765` from `singhacks-jb-wealth-intelligence`. The server scans on start and sends one "client may be exposed" alert for each client in that lane (two on 9 Nov).
6. **Retake:** each alert is sent once. To send it again, stop the server, delete `runtime/telegram_urgency_alerts.json`, and start it again.

Film the "may be exposed" alert, not the urgency alert. Urgency alerts need a score of 80 and the top score today is 76.

## Things that can change between takes

- **The review queue uses live news.** The clients under "May be exposed" change when headlines change. The script below does not name them, so it stays true. Record the queue take and the Abdullah takes on the same day.
- **Approve writes to the shared decision ledger** on the live site, and the ledger keeps every record. Tell the team before you click it. Approving one action is fine.
- **Chat answers take about 8 seconds.** Cut the wait in the edit.
- **Don't press the "What needs attention?" chip.** It currently opens with an unrelated US inflation headline. Type the question in shot 9 instead.

## Script

| # | Time | Screen | Narration |
|---|---|---|---|
| 1 | 0:00 | Slide 1 (cover) | We're SAPTrio, and this is TESSERA. Every morning it tells a relationship manager who to look at first, what doesn't add up between what a client said and what they hold, and what to do about it. |
| 2 | 0:15 | Slide 4, then slide 5 | Relationship managers spend 41% of their time on operations, not clients. Each one looks after more clients, with more complex wealth. That is where the conversation that matters gets missed. |
| 3 | 0:30 | Slide 6 (trust tax) | And news doesn't wait. In July, China announced a 20% tax on offshore trust activity. To find out who it touches, an RM checks every file by hand. TESSERA's next feature screens the whole book in seconds, and says plainly where the data is missing. |
| 4 | 0:50 | Slide 7 (Abdullah) | Or take Abdullah. His portfolio is up 26%, so every report says great year. But he asked us to build his wealth outside the Gulf and outside shipping. Look inside his structured note, and 42% is shipping and energy, the same bet as the business he owns. He also needs 5 million dollars next year, with 2.4 million in cash. |
| 5 | 1:15 | **App, home page.** Scroll slowly from the headline to the queue strip and the four lanes. | Here is TESSERA. This is the RM's morning: twenty clients, ranked. Clients a fresh headline may touch come first, so the RM can check them. Then Act now, This week and Monitor, by urgency score. Every source is labelled: a client record, a calculation, a scenario or public news. |
| 5b | 1:40 | **Phone screen recording.** The Telegram "client may be exposed" alert arrives; open it and hold on the message. | The RM doesn't have to be at the desk. When a headline may touch a client, TESSERA sends an alert with the client reference, never the name, and what to check. In the bank, this would run on the bank's own messaging. |
| 6 | 1:58 | Click **Abdullah Al-Mansoori** under Priority cases. Hover the three-part tension at the top. | Abdullah's page puts the contradiction on one screen: what he said, what the portfolio does, and the cash he needs. |
| 7 | 1:52 | Scroll to **Client vector**. Hover the drift line, Dec 2025 to Aug 2026. | This is new since SingHacks. We describe every client with 24 named measures, calculated inside the bank and never sent to a model. In what Abdullah asked to move away from, he has drifted from 29% to 42% in eight months. Below, it shows what sets him apart from the rest of the book. |
| 8 | 2:15 | Scroll to **Test the portfolio**. Click **Strait reopens**, then **Blockade worsens**. | If the Strait reopens, this illustrative scenario takes about 2 million dollars off the portfolio. It is a scenario, not a forecast, and it shows which holdings drive it. |
| 9 | 2:30 | Scroll to **Actions worth considering**. Open **Why this action** on action 1. Point at "Medium priority", then the Evidence 65 chip. | Actions come in order of what is at stake. Ring-fencing the family office money comes first: 5 million dollars due in four months. Separately, TESSERA scores how well each action is supported, and tells the RM to verify this one first. |
| 10 | 2:50 | Open **Ask TESSERA**, type: `Can Abdullah fund the USD 5m family office from cash?` Show the answer and its numbered sources. | The RM can ask questions. The answer only uses this client's records, and every line cites its source. |
| 11 | 3:02 | Click **Approve** on action 1. | And the RM decides. Approve, edit or dismiss, and the decision is recorded with its evidence. |
| 12 | 3:10 | Slide 20 (how it works) | Under the hood: code calculates, AI reads, the RM decides. Client records never leave the bank. Outside models only read public headlines. The bank's own model reviews each action, and it can only lower confidence, never raise it. |
| 13 | 3:28 | Slide 17, then slide 18 | Since SingHacks we made six shifts: client data stays in the bank, we screen instead of predict, detection works for any client, every figure says what it is, customer vectors, and actions in order of what is at stake. |
| 14 | 3:42 | Slide 24 (integration) | It plugs into what Julius Bär already runs: your research as a news feed, your portfolio data, your in-house model and your own database. |
| 15 | 3:52 | Slide 25 (ask), hold 3 seconds | Our next step is a 30-day trial with one desk. Everything you've seen is on our explainer site. Thank you. |

## Numbers in the script, checked against the live app on 9 Nov 2026

| Claim | Where it shows |
|---|---|
| 42.1% shipping and energy, looked through | Abdullah's page, top and client vector |
| Up 25.9% since Dec 2025 (said as "26%") | Headline metrics |
| USD 5.0m due from 1 Jan 2027, USD 2.4m in cash | Tension panel |
| Drift 29.4% (Dec 2025) to 42.1% (Aug 2026) | Client vector, drift line |
| Strait reopens: -6.3%, about USD 2.02m | Test the portfolio |
| Action 1: Medium priority, "USD 5.0m due in 4 months"; Evidence 65, Verify first | Actions worth considering |
| 20 clients, 24 portfolios, USD 596.2m | Home page |
| 41% of RM time on operations | Slide 4, with its source |

The trust tax screen (shot 3) is planned, not built. Keep calling it "next feature".
