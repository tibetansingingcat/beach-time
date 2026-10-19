#!/usr/bin/env python3
"""Find good beach windows in the forecast and write them to beach.ics.

Data: Open-Meteo weather + marine APIs (free, no key).
Run: python3 beach.py          -> writes beach.ics
     python3 beach.py --test   -> runs self-check
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

# --- Your beach and your rules -------------------------------------------
LAT, LON = -36.785, 175.08         # Onetangi Beach, Waiheke Island
NAME = "Beach time"
DAYS = 7                           # forecast horizon
MIN_HOURS = 2                      # shortest window worth an event

RULES = {
    "tide_ft":   lambda v: v <= 1.0,         # height vs mean sea level
    "air_f":     lambda v: 70 <= v <= 95,
    "sea_f":     lambda v: v >= 64,
    "cloud_pct": lambda v: v <= 30,          # "sunny"
    "rain_pct":  lambda v: v <= 20,
    "wind_mph":  lambda v: v <= 15,
    "is_day":    lambda v: v == 1,
}
# -------------------------------------------------------------------------

WEATHER = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&hourly=temperature_2m,cloud_cover,precipitation_probability,wind_speed_10m,is_day"
           "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=GMT&forecast_days={days}")
# ponytail: model sea level (~5 km grid), not a tide station. Swap in NOAA CO-OPS
# predictions if your beach's tide line needs to be exact.
MARINE = ("https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}"
          "&hourly=sea_surface_temperature,sea_level_height_msl"
          "&timezone=GMT&forecast_days={days}")


def get(url):
    with urllib.request.urlopen(url.format(lat=LAT, lon=LON, days=DAYS), timeout=30) as r:
        return json.load(r)["hourly"]


def hours():
    """Yield one dict per forecast hour (UTC), with all fields RULES checks."""
    w, m = get(WEATHER), get(MARINE)
    marine = dict(zip(m["time"], zip(m["sea_level_height_msl"], m["sea_surface_temperature"])))
    for i, t in enumerate(w["time"]):
        tide_m, sea_c = marine.get(t, (None, None))
        yield {
            "time": datetime.fromisoformat(t).replace(tzinfo=timezone.utc),
            "tide_ft": None if tide_m is None else tide_m * 3.281,
            "sea_f": None if sea_c is None else sea_c * 9 / 5 + 32,
            "air_f": w["temperature_2m"][i],
            "cloud_pct": w["cloud_cover"][i],
            "rain_pct": w["precipitation_probability"][i],
            "wind_mph": w["wind_speed_10m"][i],
            "is_day": w["is_day"][i],
        }


def good(h):
    return all(h[k] is not None and ok(h[k]) for k, ok in RULES.items())


def windows(hs, min_hours=MIN_HOURS):
    """Group consecutive good hours into (start, end, hours) windows."""
    out, run = [], []
    for h in list(hs) + [None]:
        if h and good(h) and (not run or h["time"] - run[-1]["time"] == timedelta(hours=1)):
            run.append(h)
            continue
        if len(run) >= min_hours:
            out.append((run[0]["time"], run[-1]["time"] + timedelta(hours=1), run))
        run = [h] if h and good(h) else []
    return out


def ics(wins):
    fmt = lambda d: d.strftime("%Y%m%dT%H%M%SZ")
    now = fmt(datetime.now(timezone.utc))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//beach-time//EN",
             f"X-WR-CALNAME:{NAME}", "REFRESH-INTERVAL;VALUE=DURATION:PT1H"]
    for start, end, run in wins:
        lo = lambda k: min(h[k] for h in run)
        hi = lambda k: max(h[k] for h in run)
        desc = (f"Air {lo('air_f'):.0f}-{hi('air_f'):.0f}F\\, sea {lo('sea_f'):.0f}F\\, "
                f"tide {lo('tide_ft'):+.1f} to {hi('tide_ft'):+.1f} ft\\, "
                f"cloud <={hi('cloud_pct')}%\\, wind <={hi('wind_mph'):.0f} mph")
        lines += ["BEGIN:VEVENT", f"UID:{fmt(start)}@beach-time", f"DTSTAMP:{now}",
                  f"DTSTART:{fmt(start)}", f"DTEND:{fmt(end)}",
                  f"SUMMARY:🏖 {NAME}", f"DESCRIPTION:{desc}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def test():
    t0 = datetime(2026, 7, 1, 18, tzinfo=timezone.utc)
    ok = dict(tide_ft=0, air_f=80, sea_f=70, cloud_pct=0, rain_pct=0, wind_mph=5, is_day=1)
    hs = [dict(ok, time=t0 + timedelta(hours=i)) for i in range(6)]
    hs[3]["cloud_pct"] = 90                       # breaks run: 0-2 good, 4-5 good
    hs[5]["tide_ft"] = None                       # missing data = not good
    w = windows(hs, min_hours=2)
    assert [(s.hour, e.hour) for s, e, _ in w] == [(18, 21)], w
    assert "DTSTART:20260701T180000Z" in ics(w)
    print("ok")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    else:
        wins = windows(hours())
        open("beach.ics", "w").write(ics(wins))
        for s, e, _ in wins:
            print(s.astimezone().strftime("%a %b %d %H:%M"), "-", e.astimezone().strftime("%H:%M"))
        print(f"{len(wins)} window(s) -> beach.ics")
