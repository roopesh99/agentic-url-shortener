# Support ticket 4412

An owner writes: "My link was clicked 3 times today according to my own server logs, all after
22:00 UTC, but the stats endpoint shows them under tomorrow's date, and today shows 0. It started
after the last release." We double-checked: the dailyClicks entry for the current UTC day is empty
and the next day's entry has the clicks.
