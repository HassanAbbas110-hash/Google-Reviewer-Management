# Connecting a business to Google

You only need this for **live** reviews. The inbox, drafts, test lab and fictional demo all work without Google.

## What I checked in Google's documentation (26 Nov 2026)

| Topic | Verified fact | Source |
|---|---|---|
| API access | Google must approve your Google Cloud project first. The applicant must manage a Business Profile that is **verified and active for 60+ days** and has a website. Apply with the "GBP API contact form", choosing *Application for Basic API Access*. If your project's quota shows **0 QPM** it is not approved yet; **300 QPM** means approved. | [Prerequisites](https://developers.google.com/my-business/content/prereqs) |
| OAuth scope | `https://www.googleapis.com/auth/business.manage` | [reviews.list](https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/list) |
| List reviews | `GET https://mybusiness.googleapis.com/v4/{accounts/*/locations/*}/reviews`, `pageSize` max 50, follow `nextPageToken`; only for verified locations | [reviews.list](https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/list) |
| Read one review | `GET .../reviews/{id}`; returns NOT_FOUND if deleted | [reviews.get](https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/get) |
| Reply | `PUT .../reviews/{id}/reply` with `{"comment": "..."}`; creates or replaces the reply | [reviews.updateReply](https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/updateReply) |
| Rate limits | 300 queries/min default; **10 edits per minute per Business Profile** (cannot be increased); over the limit returns 429 | [Usage limits](https://developers.google.com/my-business/content/limits) |
| Storing review data | Content "must be stored temporarily for no more than 30 calendar days", securely, not aggregated | [Policies](https://developers.google.com/my-business/content/policies) |
| Consent | Get the business's authorisation before replying for them; do not automate replies "without the user's prior specific and express consent" | [Policies](https://developers.google.com/my-business/content/policies) |
| Desktop sign-in | Loopback redirect (`http://127.0.0.1:port`) is still supported for Windows desktop apps; always use PKCE | [OAuth for desktop apps](https://developers.google.com/identity/protocols/oauth2/native-app) |
| Token expiry | Apps left in **Testing** status get refresh tokens that expire after **7 days**; unused tokens expire after 6 months | [OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration) |

None of the v4 review pages carried a deprecation notice when checked. I could not confirm the quota that applies specifically to the review endpoints (the limits table doesn't name them), so the app stays well under the documented limits.

**What the app does with these rules:** uses only the `business.manage` scope; walks every page; caps itself at 8 reply sends a minute per business; deletes review text and drafts after **29 days** (inside the 30-day limit) and keeps only the case record (status, staff notes) for open investigations; requires a recorded owner authorisation before any publishing and a separate opt-in for automatic replies.

A fictional demo business, an old integration, or a public listing does **not** prove API access. Only a successful sync with an approved project and an authorised account does.

## Steps (once per Google Cloud project)

1. Create a project in Google Cloud Console and apply for Business Profile API access (see Prerequisites above). Wait for approval: quota changes from 0 to 300 QPM.
2. Enable: **My Business Account Management API**, **My Business Business Information API**, and the **Google My Business API** (reviews, v4).
3. Configure the OAuth consent screen. Create an OAuth client of type **Desktop app**. Download the JSON, rename it to `credentials.json`, and put it in the app folder (next to `Start.cmd`). It is ignored by Git; never share it.
4. While the consent screen is in *Testing*, add the owner's Google account as a test user. Tokens then expire every 7 days (the app will show "Reconnect needed"). Publish the consent screen for longer-lived tokens.

## Steps (once per business)

1. In the app, add the business and note its number (shown on its page under *Google connection*).
2. Close the Review Manager window.
3. Double-click **Connect-Google.cmd**, type the business number. A browser opens: the **owner or a manager of that listing** signs in and grants access.
4. The terminal lists the locations that account manages, with addresses. Pick the one that matches the business name it shows. Publishing is switched **off** after connecting.
5. Start the app. The first sync records existing reviews as a **backlog**: they are never answered automatically. New reviews after that go through the normal inbox.

## Going live safely

1. **Draft-only pilot.** Leave publishing *Draft-only*. Let staff review and approve drafts for a couple of weeks. Owner reads a sample.
2. **Manual publishing.** Record the owner's authorisation (tick the box), switch to *Manual*. Each reply needs approval, then a confirmation screen showing the exact text and destination.
3. **Automatic.** Needs owner authorisation and checked facts. *Praise only* answers praise and blank 4-5 star ratings; *Most reviews* also answers mixed reviews and everyday complaints whose draft passed every check. Sensitive and unclear reviews, and drafts with any check note, always wait for staff. Recommended: run Manual for a few days first and read the drafts.

## When something goes wrong

| Status | Meaning | Fix |
|---|---|---|
| Reconnect needed | Token expired or access revoked | Close the app, run Connect-Google.cmd again |
| Access denied | API not approved, or the account doesn't manage the location | Check the quota (0 = not approved) and the account's role on the listing |
| Rate limited | Google's quota hit | Nothing; the app waits and retries |
| Publish result unknown | The send timed out | Open the case, press **Check Google**. The app reads Google and only marks it published if the reply is there; it never resends blindly |

**Disconnect** (business page) deletes the stored token, removes all cached review text for that business, and turns publishing off. Open investigations stay, without the review text.
