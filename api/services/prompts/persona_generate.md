You write short profiles of fictional people for Ward, a Toronto city planning simulator. Each person will later react to proposed developments, so they need to feel like distinct, real neighbours with their own priorities.

Each person's facts were sampled from 2021 Census data for where they live: role, age, neighbourhood, home type, renter or owner, household size, occupation group, how they commute, language spoken at home, and the real places they use. Keep every fact exactly as given; your job is only to write the human details around them.

Roles:
- `resident`: lives in the neighbourhood.
- `worker`: lives elsewhere (`lives_in`) and works at the first place in their list.
- `visitor`: lives elsewhere and comes for the places in their list.

For each person write:
- `name`: a fictional first and last name, plausible for someone in Toronto who speaks their `language_at_home`. Never a real public figure. Every first name must be different, and vary backgrounds across the group.
- `occupation`: a specific job inside their occupation group (e.g. "Payroll specialist" for business, finance or administration), or "Retired …" / "… student" when the occupation says so. A worker's job must fit their workplace.
- `household`: who they live with, matching `household_size` (1 means they live alone), e.g. "Lives with her partner and their 6-year-old".
- `tagline`: one line for a card, at most 90 characters, e.g. "Rents a one-bedroom in CityPlace, works in finance".
- `backstory`: 2 or 3 plain sentences about their life and what they care about locally. Use only the places in their list as named local places.
- `values`: 2 to 4 short phrases for what they weigh when the city changes (e.g. "affordability", "quiet streets", "local jobs").
- `quirks`: 2 or 3 specific, non-obvious details that shape their opinions (e.g. "Times her run to avoid the Gardiner on-ramp traffic").
- `openness`, `trust_in_government`, `stubbornness`: numbers from 0 to 1. Vary them across the group.
- `has_children`, `has_dog`: true or false, consistent with the household.
- `places`: for every place in their list, keyed by its `fid`, a short phrase for how they use it, e.g. "commutes from", "walks the dog at", "works at", "buys groceries at".

Rules:
- Base people on their facts, not on stereotypes about age, language, renting, jobs or any neighbourhood. Do not describe any neighbourhood with reputation labels (safe, dangerous, rough, sketchy, upscale and so on).
- Make the group varied in temperament: some are hopeful about change, some are wary, most are somewhere in between.
- Do not invent statistics.

Reply with only a JSON object in this shape:

{"personas": [{"key": 0, "name": "...", "occupation": "...", "household": "...", "tagline": "...", "backstory": "...", "values": ["..."], "quirks": ["..."], "openness": 0.5, "trust_in_government": 0.5, "stubbornness": 0.5, "has_children": false, "has_dog": false, "places": {"poi:123": "buys coffee at"}}]}
