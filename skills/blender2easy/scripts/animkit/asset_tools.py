"""Local browser handoffs adapted from the bundled BAS provider helpers.

These functions do not contact providers, inspect credentials or return assets.
"""
from urllib.parse import quote, urlencode


def prepare_search(provider, query):
    if provider not in ("mixamo", "pixabay"):
        raise ValueError("provider must be mixamo or pixabay")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200 or any(ord(c) < 32 for c in query):
        raise ValueError("query must contain 1–200 characters without control characters")
    query = query.strip()
    if provider == "mixamo":
        url = "https://www.mixamo.com/#/?" + urlencode({"page":"1", "query":query, "type":"Motion,MotionPack"})
        instructions = [
            "Open the URL with available browser tools and inspect actual live results.",
            "Use the user's authorized Adobe session; if sign-in is required, let the user handle it.",
            "Preview the motion and record its title, source page, character, in-place setting and download FPS.",
            "Download only when asset acquisition is in scope; verify the completed local FBX.",
            "Use assets import-motion with the downloaded file and matching FPS to create a separate Blender candidate.",
        ]
        limits = ["Imports the downloaded skeleton; it does not retarget to an existing rig."]
    else:
        url = "https://pixabay.com/sound-effects/search/" + quote(query, safe="") + "/"
        instructions = [
            "Open the URL with available browser tools and inspect actual live sound-effect results.",
            "Preview candidates and record title, creator, duration and exact source page.",
            "Before using a downloaded file, check the provider's current license and verify download completion.",
        ]
        limits = ["This browser handoff does not provide an audio search API or catalog scraper."]
    return {"schemaVersion":1, "status":"browser_required", "provider":provider, "query":query, "url":url,
            "instructions":instructions,
            "limitations":["No network request, sign-in or download has been performed.",
                           "Live results, availability and access requirements must be checked in the browser.", *limits]}
