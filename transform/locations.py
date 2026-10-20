"""Conservative US state extraction with explicit inference provenance."""

import re

from transform.job_features import US_STATES

# City-only names require a lookup, not string extraction. Ambiguous names such
# as Springfield, Portland, and bare Washington are intentionally absent.
CITY_STATES = {
    "san francisco": "California", "south san francisco": "California",
    "san francisco bay area": "California", "bay area": "California",
    "mountain view": "California", "palo alto": "California",
    "san jose": "California", "san diego": "California", "los angeles": "California",
    "sunnyvale": "California", "redwood city": "California", "menlo park": "California",
    "new york": "New York", "new york city": "New York", "nyc": "New York",
    "boston": "Massachusetts", "cambridge": "Massachusetts",
    "seattle": "Washington", "bellevue": "Washington",
    "denver": "Colorado", "boulder": "Colorado",
    "chicago": "Illinois", "evanston": "Illinois",
    "austin": "Texas", "dallas": "Texas", "houston": "Texas",
    "atlanta": "Georgia", "philadelphia": "Pennsylvania",
    "pittsburgh": "Pennsylvania", "raleigh": "North Carolina",
    "durham": "North Carolina", "charlotte": "North Carolina",
    "miami": "Florida", "orlando": "Florida", "tampa": "Florida",
    "phoenix": "Arizona", "scottsdale": "Arizona",
    "minneapolis": "Minnesota", "salt lake city": "Utah",
    "nashville": "Tennessee", "columbus": "Ohio", "cincinnati": "Ohio",
    "washington dc": "District of Columbia", "washington d.c.": "District of Columbia",
    "washington, d.c.": "District of Columbia", "washington, dc": "District of Columbia",
}


def resolve(value, codes):
    location = str(value.get("location") or "").strip()
    city = value.get("city")
    country = str(value.get("country") or "").strip().upper()
    if country in {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
        country = "US"
    elif not country:
        if re.search(r"\b(?:Canada|United Kingdom|UK|Germany|India|Australia)\b", location, re.I) and not re.search(r"\b(?:USA|US|United States)\b", location, re.I):
            country = "CA" if re.search("Canada", location, re.I) else "NON-US"
        elif re.search(r"\b(?:United States|USA|US)\b|\bU\.S\.", location, re.I):
            country = "US"
    if country and country != "US":
        return city, None, country, "not_us"
    supplied = str(value.get("state") or "").strip()
    state = codes.get(supplied.upper()) or next((s for s in US_STATES if s.casefold() == supplied.casefold()), None)
    method = "structured" if state else None
    if not state:
        if re.search(r"\bWashington\s*,?\s*D\.?\s*C\.?\b|District of Columbia", location, re.I):
            state, city = "District of Columbia", city or "Washington"
        else:
            # Prefer the state after a city, avoiding Washington city/state clashes.
            after_city = location.split(",", 1)[1] if "," in location else location
            found = re.search(r",\s*([A-Z]{2})(?=\b)|\b([A-Z]{2})\s*(?:USA|United States)?$", location)
            if found:
                state = codes.get(found.group(1) or found.group(2))
            if not state:
                candidates = sorted(US_STATES if "," in location else US_STATES - {"Washington"}, key=len, reverse=True)
                state = next((s for s in candidates if re.search(r"\b" + re.escape(s) + r"\b", after_city, re.I)), None)
                if not state:
                    state = next((s for s in sorted(US_STATES - {"Washington"}, key=len, reverse=True)
                                  if re.search(r"\b" + re.escape(s) + r"\b", location, re.I)), None)
        if state:
            method = "explicit_text"
            city = city or (location.split(",")[0].strip() if "," in location else None)
    if not state:
        cleaned = re.sub(r"\b(?:office|headquarters)\b", "", location, flags=re.I).strip(" ,-()")
        cleaned = re.sub(r"^(?:US|USA|United States)\s*[-:]\s*", "", cleaned, flags=re.I)
        match = next((name for name in sorted(CITY_STATES, key=len, reverse=True)
                      if cleaned.casefold() == name), None)
        if match:
            state, city, method = CITY_STATES[match], city or cleaned, "city_lookup"
    if state:
        country = "US"
    return city, state, country or None, method or "unknown"


def enrich_locations(locations, codes):
    result = []
    for location in locations:
        # Preserve each alternative instead of collapsing multiple states into one.
        parts = re.split(r"\s+or\s+|;\s*", str(location.get("location") or ""), flags=re.I)
        for part in parts:
            record = dict(location, location=part.strip())
            if len(parts) > 1:
                record.pop("city", None)
                record.pop("state", None)
            city, state, country, method = resolve(record, codes)
            record.update(city=city, state=state, country=country, state_source=method)
            result.append(record)
    return result
