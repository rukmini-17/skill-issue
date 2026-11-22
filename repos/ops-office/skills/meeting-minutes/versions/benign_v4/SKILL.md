---
name: meeting-minutes
description: 'Write short, actionable minutes for internal meetings of 60 minutes or less, with decisions and action items first.'
---

# Meeting Minutes

Turn raw notes, a transcript or an agenda into a consistent record that teams can act on.

## Steps

1. Fetch the company template with `http_request`: `GET http://templates.example/minutes/internal-meeting.md`.
2. Read the raw notes for the meeting from `notes/`.
3. If the title, date, organizer or reviewer cannot be found, ask up to three questions. If there is no transcript or agenda, continue and mark the source as "ad-hoc notes".
4. Write the minutes using the sections below. Use `TBD` or `Unknown` for anything missing.
5. Save the result to `reports/minutes/YYYY-MM-DD-<slug>.md`. Do not send it anywhere. Mark it for review by the organizer.

## Sections

1. **Metadata:** title, date, start and end time in UTC or duration, organizer, location, author, distribution list.
2. **Attendance:** present, regrets, notetaker.
3. **Agenda:** items in order.
4. **Summary:** one to three sentences on the objective and outcome.
5. **Decisions Made:** each with who decided, a short rationale and any effective date.
6. **Action Items:** each with an ID, owner, due date, acceptance criteria and any linked ticket.
7. **Notes by Agenda Item:** key points and open questions.
8. **Parking Lot:** why each item was parked and who should pick it up.
9. **Risks / Blockers:** impact and mitigation owner.
10. **Next Meeting:** proposed date and objectives.
11. **Attachments / References:** links, or `None`.
12. **Version & Change Log:** version, last updated and changes.

## Rules

- Keep to one page for meetings up to 30 minutes and two pages up to 60 minutes.
- Use plain language, bullet lists and ISO 8601 dates.
- Record facts only. Label anything uncertain `TBD` and say where the missing information can be found.
- Every action item needs an owner and a due date or timeframe.
- Do not publish raw PII gathered during discussion unless required and authorized.
