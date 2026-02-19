#!/usr/bin/env python3
"""
songfly_optimizer.py — Songfly Campaign Optimizer
===================================================
Automates campaign optimization based on SPV (Spotify Popularity Value) costs.

Logic:
  1. Scrape the dashboard table.
  2. Skip campaigns where Days < 2, status is Paused/RejectedByChannel,
     or SPV Cost is already within threshold.
  3. For eligible campaigns:
       Step 1 — Interest Swap: pick a broader interest from the genre map and
                swap it in on the Targeting tab.
       Step 2 — Creative Swap: if all interests are exhausted, add stock footage
                on the Creative tab using a genre-relevant search term.

Usage:
  pip install -r requirements.txt
  playwright install chromium
  python songfly_optimizer.py
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

# ── Configuration ─────────────────────────────────────────────────────────────

SONGFLY_URL = "https://app.songfly.io"   # adjust if your dashboard lives elsewhere
SPV_COST_THRESHOLD = 0.50                # dollars — campaigns above this are optimised
MIN_DAYS = 2                             # campaigns must be running for at least this many days

SESSION_FILE = Path("session.json")      # saved auth state so you only log in once
STATE_FILE   = Path("optimizer_state.json")  # tracks per-campaign optimisation history

# ── Genre → Interest candidates ───────────────────────────────────────────────
# Ordered from most specific/targeted to broadest. The optimizer works through
# the list and picks the first interest that hasn't been tried yet.

GENRE_INTERESTS: dict[str, list[str]] = {
    "hip hop":    ["Festival", "Live Music", "Urban Culture", "Street Art",    "Dance Music"],
    "rap":        ["Festival", "Live Music", "Urban Culture", "Street Style",  "Trap Music"],
    "pop":        ["Concerts", "Pop Culture", "Music Videos", "Entertainment", "Dancing"],
    "rock":       ["Live Concert", "Alternative Music", "Music Festival",      "Indie Music", "Guitar"],
    "r&b":        ["Neo Soul", "Smooth Music", "Chill Vibes", "Love Songs",    "Soul Music"],
    "soul":       ["Neo Soul", "Blues Music", "Smooth Jazz", "Gospel",         "Rhythm and Blues"],
    "electronic": ["Dance Music", "Festival", "Nightlife", "DJ Culture",       "Rave"],
    "edm":        ["Dance Music", "Festival", "Nightlife", "Electronic Music", "Club Music"],
    "country":    ["Americana", "Folk Music", "Southern Music", "Roots Music", "Country Life"],
    "jazz":       ["Jazz Club", "Blues Music", "Soul Music", "Lounge Music",   "Smooth Jazz"],
    "classical":  ["Orchestra", "Concert Hall", "Instrumental Music",          "Fine Arts",   "Symphony"],
    "latin":      ["Latin Pop", "Reggaeton", "Salsa", "World Music",           "Latin Culture"],
    "reggae":     ["Island Music", "World Music", "Roots Music", "Dancehall",  "Ska"],
    "blues":      ["Soul Music", "Jazz", "Roots Music", "Americana",          "Folk"],
    "folk":       ["Americana", "Acoustic Music", "Indie Folk",                "Singer-Songwriter", "Roots"],
    "metal":      ["Rock Music", "Heavy Music", "Concert", "Alternative",      "Hard Rock"],
    "indie":      ["Alternative Music", "Indie Culture", "DIY Music",          "Underground Music", "Art"],
}

# ── Genre → Stock footage search terms ────────────────────────────────────────

GENRE_FOOTAGE: dict[str, list[str]] = {
    "hip hop":    ["concert", "urban music", "freestyle rap"],
    "rap":        ["concert", "hip hop",     "urban beats"],
    "pop":        ["concert", "music performance", "pop show"],
    "rock":       ["rock concert", "guitar performance", "stage show"],
    "r&b":        ["soul music", "r&b performance", "smooth vibes"],
    "soul":       ["soul performance", "gospel choir", "music vibes"],
    "electronic": ["dj set", "electronic concert", "rave lights"],
    "edm":        ["festival lights", "dj performance", "dance crowd"],
    "country":    ["country concert", "acoustic guitar", "southern music"],
    "jazz":       ["jazz club", "saxophone", "smooth jazz"],
    "classical":  ["orchestra", "violin performance", "concert hall"],
    "latin":      ["latin dance", "salsa", "latin music festival"],
    "reggae":     ["island music", "reggae concert", "tropical vibes"],
    "blues":      ["blues guitar", "blues concert", "soulful music"],
    "folk":       ["acoustic concert", "folk music", "singer songwriter"],
    "metal":      ["metal concert", "guitar shred", "rock performance"],
    "indie":      ["indie concert", "indie music", "alternative show"],
}

DEFAULT_INTERESTS = ["Music", "Live Music", "Concert", "Music Festival", "Entertainment"]
DEFAULT_FOOTAGE   = ["concert", "music performance", "live show"]

# ── Genre helpers ─────────────────────────────────────────────────────────────

def _match_genre(genre: str, mapping: dict[str, list]) -> list:
    """Return the best matching list from *mapping* for a given genre string."""
    genre_lower = genre.lower()
    for key, value in mapping.items():
        if key in genre_lower:
            return value
    return []


def suggest_interest(genre: str, used_interests: list[str]) -> Optional[str]:
    """Return the first genre interest not yet tried, or None if all are exhausted."""
    candidates = _match_genre(genre, GENRE_INTERESTS) or DEFAULT_INTERESTS
    for interest in candidates:
        if interest not in used_interests:
            return interest
    return None


def footage_search_term(genre: str) -> str:
    """Return the primary stock-footage search term for a genre."""
    terms = _match_genre(genre, GENRE_FOOTAGE) or DEFAULT_FOOTAGE
    return terms[0]

# ── State persistence ─────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_campaign_state(state: dict, campaign_id: str) -> dict:
    return state.get(campaign_id, {"interest_swaps": [], "creative_swapped": False})


def set_campaign_state(state: dict, campaign_id: str, c_state: dict) -> None:
    state[campaign_id] = c_state
    save_state(state)

# ── Logging ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_ts()}] {msg}")


def log_action(action: str, reason: str) -> None:
    bar = "─" * 60
    print(f"\n{bar}")
    print(f"  ACTION : {action}")
    print(f"  REASON : {reason}")
    print(f"{bar}\n")

# ── Browser / session management ──────────────────────────────────────────────

async def launch_browser(pw) -> tuple[Browser, BrowserContext]:
    browser = await pw.chromium.launch(headless=False, slow_mo=150)
    if SESSION_FILE.exists():
        log("Loading saved session from session.json …")
        context = await browser.new_context(storage_state=str(SESSION_FILE))
    else:
        log("No saved session found — will prompt for manual login.")
        context = await browser.new_context()
    return browser, context


async def ensure_logged_in(page: Page) -> None:
    """Navigate to the dashboard; if redirected to a login page, wait for the user."""
    await page.goto(SONGFLY_URL, wait_until="networkidle")

    is_auth_page = any(kw in page.url for kw in ("login", "signin", "auth", "sign-in"))
    if is_auth_page:
        print("\n" + "=" * 60)
        print("  MANUAL LOGIN REQUIRED")
        print("  Log in to Songfly in the browser window that just opened.")
        print("  The script will resume automatically once you're logged in.")
        print("=" * 60 + "\n")

        await page.wait_for_url(
            lambda url: not any(kw in url for kw in ("login", "signin", "auth", "sign-in")),
            timeout=120_000,
        )
        log("Login detected — saving session to session.json …")
        await page.context.storage_state(path=str(SESSION_FILE))
        log("Session saved. Future runs will skip the login step.")
    else:
        log("Session is valid — already logged in.")

# ── Dashboard scraping ────────────────────────────────────────────────────────

async def scrape_campaigns(page: Page) -> list[dict]:
    """
    Navigate to the campaigns list and parse every table row.

    Column order assumed (adjust indices / selectors to match the live DOM):
      0: Campaign / Song name   ("ArtistName – SongName" or just a label)
      1: Status
      2: Days
      3: SPV Cost               (e.g. "$0.37")
      4: Genre

    Each campaign row is expected to carry a data-id attribute or a clickable link.
    """
    log("Navigating to /campaigns …")
    await page.goto(f"{SONGFLY_URL}/campaigns", wait_until="networkidle")
    await page.wait_for_timeout(2_000)

    campaigns: list[dict] = []
    rows = await page.query_selector_all("table tbody tr")

    if not rows:
        log("WARNING: No <table tbody tr> rows found. "
            "Inspect the live page and adjust the selector if needed.")
        return campaigns

    for row in rows:
        cells = await row.query_selector_all("td")
        if len(cells) < 4:
            continue

        try:
            raw_name     = (await cells[0].inner_text()).strip()
            raw_status   = (await cells[1].inner_text()).strip()
            raw_days     = (await cells[2].inner_text()).strip()
            raw_spv_cost = (await cells[3].inner_text()).strip()
            raw_genre    = (await cells[4].inner_text()).strip() if len(cells) > 4 else "Pop"

            days     = int(re.sub(r"[^\d]", "", raw_days)     or 0)
            spv_cost = float(re.sub(r"[^\d.]", "", raw_spv_cost) or 0.0)

            # Prefer an explicit data-id on the row; fall back to slugified name
            campaign_id = (await row.get_attribute("data-id")) or re.sub(r"\W+", "_", raw_name.lower())

            # Split "Artist – Song" if the name cell combines them
            if "–" in raw_name:
                artist, song = (p.strip() for p in raw_name.split("–", 1))
            elif " - " in raw_name:
                artist, song = (p.strip() for p in raw_name.split(" - ", 1))
            else:
                artist, song = raw_name, raw_name

            campaigns.append({
                "id":     campaign_id,
                "name":   raw_name,
                "artist": artist,
                "song":   song,
                "genre":  raw_genre,
                "status": raw_status,
                "days":   days,
                "spv_cost": spv_cost,
                "row":    row,
            })

        except Exception as exc:
            log(f"  Skipping malformed row: {exc}")

    log(f"Scraped {len(campaigns)} campaign(s).")
    return campaigns


def filter_campaigns(campaigns: list[dict]) -> list[dict]:
    """Return only campaigns that need optimisation, with verbose skip reasons."""
    eligible: list[dict] = []
    for c in campaigns:
        name = c["name"]
        if c["days"] < MIN_DAYS:
            log(f"  SKIP  '{name}': {c['days']} day(s) running (need ≥ {MIN_DAYS})")
            continue
        if c["status"] in ("Paused", "RejectedByChannel"):
            log(f"  SKIP  '{name}': status is '{c['status']}'")
            continue
        if c["spv_cost"] <= SPV_COST_THRESHOLD:
            log(f"  OK    '{name}': SPV Cost ${c['spv_cost']:.2f} ≤ ${SPV_COST_THRESHOLD:.2f} — no action needed")
            continue
        log(f"  FLAG  '{name}': SPV Cost ${c['spv_cost']:.2f} > ${SPV_COST_THRESHOLD:.2f} — will optimise")
        eligible.append(c)
    return eligible

# ── In-campaign navigation helpers ───────────────────────────────────────────

async def open_campaign(page: Page, campaign: dict) -> bool:
    """Click the campaign's table row (or its first link) to open the detail view."""
    try:
        link = await campaign["row"].query_selector("a")
        if link:
            await link.click()
        else:
            await campaign["row"].click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1_500)
        return True
    except Exception as exc:
        log(f"  ERROR opening campaign: {exc}")
        return False


async def go_to_tab(page: Page, tab_name: str) -> bool:
    """Activate a named tab inside the campaign detail view."""
    selectors = [
        f"[role='tab']:has-text('{tab_name}')",
        f"button:has-text('{tab_name}')",
        f"a:has-text('{tab_name}')",
        f"li:has-text('{tab_name}')",
    ]
    for sel in selectors:
        tab = await page.query_selector(sel)
        if tab:
            await tab.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(1_000)
            return True
    log(f"  WARNING: Tab '{tab_name}' not found (tried {len(selectors)} selectors).")
    return False

# ── Optimisation Step 1 — Interest Swap ──────────────────────────────────────

async def do_interest_swap(
    page: Page,
    campaign: dict,
    new_interest: str,
    old_interests: list[str],
) -> bool:
    """
    On the Targeting tab:
      1. Remove any existing interest tag(s) that are performing poorly.
      2. Add *new_interest*.
      3. Save.
    """
    log(f"  Opening '{campaign['name']}' …")
    if not await open_campaign(page, campaign):
        return False

    log("  → Targeting tab")
    if not await go_to_tab(page, "Targeting"):
        await page.go_back()
        return False

    # — Remove existing interests —
    removed = 0
    try:
        # Common tag/chip patterns — extend as needed for the live DOM
        tag_selectors = [
            ".interest-tag",
            "[data-testid='interest-tag']",
            ".chip",
            ".tag",
            ".targeting-tag",
        ]
        for sel in tag_selectors:
            tags = await page.query_selector_all(sel)
            for tag in tags:
                close = await tag.query_selector("button, .close, .remove, [aria-label='remove'], [aria-label='Remove']")
                if close:
                    tag_text = (await tag.inner_text()).strip()
                    log(f"    Removing interest: '{tag_text}'")
                    await close.click()
                    await page.wait_for_timeout(500)
                    removed += 1
            if removed:
                break   # stop after the first selector that matched

        if not removed:
            log("    No removable interest tags found — will just add the new one.")
    except Exception as exc:
        log(f"    WARNING removing interests: {exc}")

    # — Type the new interest —
    try:
        input_selectors = [
            "input[placeholder*='interest' i]",
            "input[name='interest']",
            ".targeting-section input",
            ".interests-input input",
            "[data-testid='interest-input']",
        ]
        interest_input = None
        for sel in input_selectors:
            interest_input = await page.query_selector(sel)
            if interest_input:
                break

        if not interest_input:
            log("    WARNING: Interest input not found. Selectors may need adjustment.")
            await page.go_back()
            return False

        await interest_input.fill(new_interest)
        await page.wait_for_timeout(800)

        # Accept suggestion dropdown or press Enter
        suggestion = await page.query_selector(
            f"[role='option']:has-text('{new_interest}'), "
            f"li.autocomplete-item:has-text('{new_interest}')"
        )
        if suggestion:
            await suggestion.click()
        else:
            add_btn = await page.query_selector("button:has-text('Add'), button[type='submit']")
            if add_btn:
                await add_btn.click()
            else:
                await interest_input.press("Enter")

        await page.wait_for_timeout(800)
        log(f"    Added new interest: '{new_interest}'")

    except Exception as exc:
        log(f"    ERROR entering interest: {exc}")
        await page.go_back()
        return False

    # — Save —
    try:
        save_btn = await page.query_selector(
            "button:has-text('Save Changes'), button:has-text('Save'), button[type='submit']"
        )
        if save_btn:
            await save_btn.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(1_000)
            log("    Targeting saved.")
        else:
            log("    WARNING: Save button not found — changes may not be persisted.")
    except Exception as exc:
        log(f"    WARNING saving: {exc}")

    await page.go_back()
    await page.wait_for_load_state("networkidle")
    return True

# ── Optimisation Step 2 — Creative Swap ──────────────────────────────────────

async def do_creative_swap(page: Page, campaign: dict) -> bool:
    """
    On the Creative tab:
      1. Click 'Add Stock Footage'.
      2. Search with a genre-specific term.
      3. Select the first result.
      4. Save.
    """
    log(f"  Opening '{campaign['name']}' …")
    if not await open_campaign(page, campaign):
        return False

    log("  → Creative tab")
    if not await go_to_tab(page, "Creative"):
        await page.go_back()
        return False

    search_term = footage_search_term(campaign["genre"])
    log(f"    Stock footage search term: '{search_term}' (genre: {campaign['genre']})")

    # — Click 'Add Stock Footage' —
    try:
        btn_selectors = [
            "button:has-text('Add Stock Footage')",
            "button:has-text('Stock Footage')",
            "[data-testid='add-stock-footage']",
            "button:has-text('Add Video')",
        ]
        stock_btn = None
        for sel in btn_selectors:
            stock_btn = await page.query_selector(sel)
            if stock_btn:
                break

        if not stock_btn:
            log("    WARNING: 'Add Stock Footage' button not found.")
            await page.go_back()
            return False

        await stock_btn.click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1_500)

    except Exception as exc:
        log(f"    ERROR clicking Add Stock Footage: {exc}")
        await page.go_back()
        return False

    # — Search —
    try:
        search_selectors = [
            "input[placeholder*='search' i]",
            "input[placeholder*='Search']",
            "input[name='search']",
            ".footage-search input",
            "[data-testid='footage-search']",
        ]
        search_input = None
        for sel in search_selectors:
            search_input = await page.query_selector(sel)
            if search_input:
                break

        if search_input:
            await search_input.fill(search_term)
            await search_input.press("Enter")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2_000)
            log(f"    Searched for: '{search_term}'")
        else:
            log("    WARNING: Search input not found in stock footage modal.")

    except Exception as exc:
        log(f"    WARNING searching footage: {exc}")

    # — Select first result —
    try:
        result_selectors = [
            ".footage-item",
            ".stock-video-item",
            "[data-testid='footage-item']",
            ".video-result",
            ".media-item",
            ".asset-card",
        ]
        items = []
        for sel in result_selectors:
            items = await page.query_selector_all(sel)
            if items:
                break

        if not items:
            log("    WARNING: No stock footage results found.")
            close = await page.query_selector(
                "button:has-text('Cancel'), button[aria-label='close'], .modal-close, [data-testid='modal-close']"
            )
            if close:
                await close.click()
            await page.go_back()
            return False

        await items[0].click()
        await page.wait_for_timeout(1_000)
        log("    Selected the first stock footage result.")

    except Exception as exc:
        log(f"    ERROR selecting footage: {exc}")
        await page.go_back()
        return False

    # — Confirm selection —
    try:
        confirm_selectors = [
            "button:has-text('Select')",
            "button:has-text('Use This')",
            "button:has-text('Add')",
            "button:has-text('Confirm')",
            "button:has-text('Apply')",
        ]
        for sel in confirm_selectors:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(1_000)
                break

    except Exception as exc:
        log(f"    WARNING confirming selection: {exc}")

    # — Save the creative —
    try:
        save_btn = await page.query_selector(
            "button:has-text('Save Changes'), button:has-text('Save'), button[type='submit']"
        )
        if save_btn:
            await save_btn.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(1_000)
            log("    Creative saved.")
        else:
            log("    WARNING: Save button not found — creative changes may not be persisted.")

    except Exception as exc:
        log(f"    WARNING saving creative: {exc}")

    await page.go_back()
    await page.wait_for_load_state("networkidle")
    return True

# ── Per-campaign optimisation decision tree ───────────────────────────────────

async def optimise_campaign(page: Page, campaign: dict, state: dict) -> None:
    cid     = campaign["id"]
    c_state = get_campaign_state(state, cid)

    interest_swaps  = c_state.get("interest_swaps", [])
    creative_swapped = c_state.get("creative_swapped", False)

    print()
    log(f"Campaign  : {campaign['name']}")
    log(f"Artist    : {campaign['artist']}")
    log(f"Genre     : {campaign['genre']}")
    log(f"SPV Cost  : ${campaign['spv_cost']:.2f}  |  Days: {campaign['days']}  |  Status: {campaign['status']}")
    log(f"History   : interest_swaps={interest_swaps}  creative_swapped={creative_swapped}")

    # ── Step 1: Interest swap ─────────────────────────────────────────────────
    if not creative_swapped:
        new_interest = suggest_interest(campaign["genre"], interest_swaps)

        if new_interest:
            log_action(
                f"Interest Swap → '{new_interest}'",
                f"SPV Cost ${campaign['spv_cost']:.2f} exceeds ${SPV_COST_THRESHOLD:.2f} threshold. "
                f"Genre '{campaign['genre']}' — broadening audience targeting. "
                f"Previous swaps tried: {interest_swaps if interest_swaps else 'none'}.",
            )
            success = await do_interest_swap(page, campaign, new_interest, interest_swaps)
            if success:
                interest_swaps.append(new_interest)
                c_state["interest_swaps"] = interest_swaps
                set_campaign_state(state, cid, c_state)
                log(f"  Done. Cumulative interest swaps: {interest_swaps}")
                return

        log(f"  All genre interests exhausted ({interest_swaps}). Escalating to creative swap.")

    # ── Step 2: Creative swap ─────────────────────────────────────────────────
    log_action(
        "Creative Swap — Add Stock Footage",
        f"SPV Cost ${campaign['spv_cost']:.2f} exceeds ${SPV_COST_THRESHOLD:.2f} threshold. "
        f"Interest pool exhausted (tried: {interest_swaps}). "
        f"Refreshing ad creative with genre-relevant stock footage.",
    )
    success = await do_creative_swap(page, campaign)
    if success:
        c_state["creative_swapped"] = True
        set_campaign_state(state, cid, c_state)
        log("  Done. Creative swapped.")

# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    print()
    print("=" * 60)
    print("  SONGFLY CAMPAIGN OPTIMIZER")
    print(f"  SPV Cost threshold : > ${SPV_COST_THRESHOLD:.2f}")
    print(f"  Minimum days       : >= {MIN_DAYS}")
    print("=" * 60)
    print()

    state = load_state()

    async with async_playwright() as pw:
        browser, context = await launch_browser(pw)
        page = await context.new_page()

        try:
            await ensure_logged_in(page)

            campaigns = await scrape_campaigns(page)

            log("\n─── Filtering campaigns ───")
            eligible = filter_campaigns(campaigns)
            print()
            log(f"{len(eligible)} campaign(s) flagged for optimisation.")

            if not eligible:
                log("Nothing to do — all campaigns are healthy or ineligible.")
            else:
                for campaign in eligible:
                    await optimise_campaign(page, campaign, state)

        except Exception as exc:
            log(f"FATAL: {exc}")
            raise

        finally:
            await page.wait_for_timeout(2_000)
            await context.close()
            await browser.close()

    print()
    print("=" * 60)
    print("  RUN COMPLETE")
    print("=" * 60)
    print()


if __name__ == "__main__":
    asyncio.run(main())
