---
name: incident-postmortem
description: 'Write a structured, blameless post-mortem after an outage, incident, serious degradation or near miss. Use for "post-mortem", "incident review", "outage report", "root cause analysis" or "RCA".'
---

# Incident Post-Mortem

Build shared understanding, find root causes without blame and leave with concrete actions. Systems fail, not people: write "the alert did not fire", not "X forgot to". Skip this for minor staging bugs and planned maintenance.

## Process

1. **Gather facts.** Start from the incident notes in `notes/` and ask for anything missing. You need the title, times, severity, affected services and a rough timeline.
2. **Build the timeline.** List events in order with UTC times, and flag gaps worth checking in logs.
3. **Find the root cause.** Ask "why" repeatedly until you reach a system or process gap that can be fixed. Keep one or two root causes, and list other conditions as contributing factors. "Human error" is never a root cause.
4. **Quantify impact.** Separate detection-to-resolution time from symptom start. Give peak error rate against baseline and the share of traffic affected.
5. **Assign actions.** Give each root cause and contributing factor at least one specific action, with a named owner and a due date. "Improve monitoring" is too vague.
6. **Write it up.** Save the document to `docs/postmortems/YYYY-MM-DD-<slug>.md`, ideally within 72 hours.

## Document sections

Start with `# Post-Mortem: [Incident Title]`, followed by the date, severity, duration, incident commander and status. Then use these headings:

- `## Summary`: two or three sentences for someone who was not involved
- `## Impact`: services, user impact, users affected, peak error rate, data loss, SLA breach
- `## Timeline`: a table of UTC times and events
- `## Root Cause`
- `## Contributing Factors`
- `## What Went Well`
- `## What Could Have Gone Better`
- `## Action Items`: a table of action, owner, due date and priority
- `## Lessons Learned`: optional
