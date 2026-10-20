# Fake data

Sample data so everyone can build before the real pipeline works.

- **Sample A:** hand-crafted 10-minute slice, ~120 events, every event type at least once
- **Sample B:** script-generated full match, ~1,200 events
- **Tracking sample:** one minute at 25 fps

Every file here must pass `python scripts/validate.py`.
