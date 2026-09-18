# Captured curl sessions

Each file here is a raw `curl` command captured from a real browser
session on the corresponding OTA. They carry the cookies, WAF tokens,
and request headers that let each client bypass the site's bot
detection. They are **not** tracked in git.

## Expected files

    booking_com.curl
    agoda_com.curl
    trip_com.curl
    expedia_com.curl
    tripadvisor_com.curl

## How to capture

1. Open the OTA in a real browser (Chrome recommended).
2. Navigate to any real property page.
3. Open DevTools -> Network.
4. Reload the page (Ctrl+R).
5. Right-click the top-level document request
   -> Copy -> Copy as cURL (bash).
6. Save that command verbatim to the corresponding `.curl` file.

The parser `profile_plugins/curl_parser.py` extracts headers and
cookies; the URL inside the curl is ignored.

## When to recapture

The client writes a flag file when a session goes stale:

    sub_profiles/<ota>.session_expired

When you see it, recapture the `.curl` file and delete the flag:

    rm sub_profiles/<ota>.session_expired
