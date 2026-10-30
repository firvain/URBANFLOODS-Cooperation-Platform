# Privacy Policy — URBANFLOODS Cooperation Platform

**Version 1 (draft for legal review), 31 October 2026.** This is the text the platform's
`/privacy` page will show (increment 5e). It describes how personal data is processed when you
use https://cooperation.urbanfloods.app. Items marked **[CHECK]** need confirmation by the
University of Western Macedonia's legal office before go-live.

---

## 1. Who is responsible

The data controller is the **University of Western Macedonia (UOWM)**, Active Urban Planning
Zone (ZEP) I, 50100 Kozani, Greece, acting as Lead Partner of the project URBANFLOODS
(IPA-ADRION00374), co-funded by the European Union through the Interreg IPA ADRION programme
2021–2027.

Contact for all questions and requests about personal data: Prof. Malamati Louta, Scientific
Coordinator, louta@uowm.gr. **[CHECK: whether UOWM's institutional Data Protection Officer must
also be named, per Greek Law 4624/2019]**

## 2. What this platform is

The Platform is the project's cooperation and knowledge-exchange tool. Everything published on it
can be read without an account. An account is needed to post, reply, comment, report content, or
be listed in the members directory. We collect only what is needed to run the service and to
report on the project to the programme that funds it.

## 3. What data we process, why, and on which legal basis

### 3.1 Visitors (no account)

| Data | Purpose | Legal basis | Retention |
|---|---|---|---|
| Technical access logs: IP address, date and time, requested page, browser type, referring page | Security, abuse prevention, troubleshooting | Legitimate interest in running a secure service (GDPR art. 6(1)(f)) | Web server logs are rotated and deleted after 14 days. IP addresses are never stored in the platform database. |
| Rate-limiting counters keyed by a keyed hash of the IP address | Protection against brute-force and abuse | Legitimate interest (art. 6(1)(f)) | In memory only; expire within minutes to hours |
| Language preference (`locale`) | Show the interface in your language | Strictly necessary to provide the service you asked for | Stored in your browser only (local storage), until you clear it |

### 3.2 Registered members

| Data | Purpose | Legal basis | Retention |
|---|---|---|---|
| Email address (verified), password (stored only as an argon2id hash) | Create and secure your account; send verification, password-reset and notification emails | Performance of the agreement you enter by registering (art. 6(1)(b)) | Until you delete your account (then anonymised, section 7). Unverified accounts are deleted automatically after 30 days. |
| Display name, optional organisation (from the partner list or free text), country, interface language, short biography, expertise areas | Your public member profile, the members directory, suggested collaborators, and attribution of your contributions | Performance of the agreement (art. 6(1)(b)); for the directory and email visibility, your choice in the account settings (consent, art. 6(1)(a), which you can withdraw at any time by changing the setting) | Until you delete your account |
| Your contributions: posts, threads, replies, comments, uploaded images and their descriptions, links to KNOWBASE items | The purpose of the Platform: knowledge exchange among stakeholders; published under the CC BY 4.0 licence (Terms of Use, section 8) | Performance of the agreement (art. 6(1)(b)) and public interest in the implementation of an EU co-funded project (art. 6(1)(e)) | Kept on the Platform; after account deletion attributed to "Deleted user" (section 7) |
| Session cookie (`uf_session`, random identifier, HttpOnly, Secure, SameSite=Lax) | Keep you signed in; protect against cross-site request forgery | Strictly necessary for the service you requested (no consent required under the ePrivacy rules) | 30 days of inactivity, or until you sign out or revoke the session from your account page |
| Session list: creation time, last activity, expiry, browser description (user agent) | Let you see and sign out your devices; security | Performance of the agreement (art. 6(1)(b)) | Expired and revoked sessions are deleted after 7 days |
| Audit log: time-stamped record of actions on your account and content (registration and consent, verification, sign-in and failed sign-in, profile and settings changes, password and email changes, moderation decisions about your content, data export, deletion) | Security, accountability of moderation, evidence of your consent, and project reporting | Legitimate interest (art. 6(1)(f)) and legal obligation to keep records for the funded project (art. 6(1)(c)) | For the life of the Platform and the statutory retention period of the Interreg IPA ADRION programme **[CHECK: retention per the subsidy contract]**. Audit entries never contain passwords, tokens or IP addresses. |
| Notification preferences | Send you only the emails you want | Performance of the agreement (art. 6(1)(b)) | Until you delete your account |
| Reports you make about content, and reports made about your content | Moderation | Legitimate interest in keeping the Platform safe (art. 6(1)(f)) | For the life of the Platform |

### 3.3 Admins (project partners)

Members with the admin role additionally appear as the actor of moderation and user-management
actions in the audit log. The exported data of another member never reveals which admin acted.

### 3.4 Bot check at registration

To keep out automated sign-ups, the registration, resend-verification and password-reset forms use
**Cloudflare Turnstile**. Turnstile analyses browser signals to decide whether the request comes
from a person; it sets no tracking cookie in normal operation. Cloudflare's processing is described
in its privacy policy (https://www.cloudflare.com/privacypolicy/). Legal basis: legitimate interest
in preventing abuse (art. 6(1)(f)). **[CHECK: confirm Turnstile is enabled in production; if it is
not, delete this section]**

## 4. Data we do not collect

- No special categories of personal data (health, ethnic origin, political opinions, religious
  beliefs, trade-union membership, genetic or biometric data, sex life or orientation). The project
  committed in its application not to process such data, and the Terms of Use prohibit posting it
  about yourself or others.
- No analytics, advertising or tracking cookies, and no social-media plug-ins. The only cookie set
  by the Platform is the session cookie listed above. No cookie banner is shown because no
  consent-based cookie exists.
- No profiling or automated decision-making with legal or similarly significant effects. The
  "suggested collaborators" list simply matches expertise areas you chose to publish.

## 5. Who receives the data

- **Hosting:** the Platform runs on a server operated by the University of Western Macedonia
  (TELNAS laboratory) **[CHECK: server operator and location]**. Backups are stored on the same
  infrastructure.
- **Cloudflare, Inc.:** DNS, content delivery and protection (all traffic to the Platform passes
  through Cloudflare's network) and the Turnstile bot check. Cloudflare acts as a processor under
  its data processing addendum; transfers outside the EU are covered by the EU Standard Contractual
  Clauses and the EU-US Data Privacy Framework. **[CHECK: Cloudflare account holder and DPA]**
- **Google LLC (Gmail):** transactional emails (verification, password reset, email change,
  notifications, admin digests) are sent through a Gmail account operated by the project. Google
  processes the recipient address and message content as a processor under Google's terms.
  **[CHECK: consider an institutional SMTP server to keep email within UOWM]**
- **Project partners:** admins from the URBANFLOODS partner organisations see member profiles and
  content in the course of moderation. Aggregated, non-identifying statistics (numbers of members by
  country and organisation, numbers of contributions) are reported to the Interreg IPA ADRION
  programme as output indicators. Your name is not reported unless you are an admin acting on
  behalf of a partner.
- **Public:** your display name, organisation, country, biography, expertise areas and
  contributions are public by design when you appear in the directory or publish content. Your
  email address is shown to other members only if you switch that on.
- **Authorities:** we disclose data when required by law, a court or a competent authority,
  including programme audit and control bodies.

We do not sell personal data and do not use it for marketing.

## 6. Security

Passwords are hashed with argon2id and never stored in clear. Sessions use random tokens stored
only as hashes. All traffic is encrypted (HTTPS). Access to the server is restricted to the
technical team by key-based authentication. Content you submit is sanitised to prevent script
injection. Every security-relevant action is written to the audit log. The database is backed up
regularly; backups are kept for 14 days **[CHECK]**.

## 7. How long we keep data, and what happens when you delete your account

- You can delete your account at any time from your account settings. Deletion is immediate and
  anonymising: your email address, display name, organisation, country, biography, expertise and
  settings are erased, your password hash is removed, and all your sessions and pending email links
  are cancelled.
- Your contributions remain on the Platform under the CC BY 4.0 licence you granted when posting,
  attributed to "Deleted user", so that discussions other members took part in stay intact. If you
  want particular contributions removed as well, say so when deleting or write to us; we remove them
  unless we are legally required to keep them.
- Audit log entries about the deleted account are kept, without any identifying data, for
  accountability and project reporting.
- Unverified accounts are deleted automatically 30 days after registration.
- Email tokens expire after 1 to 48 hours and are deleted 7 days after expiry.

## 8. Your rights

Under the GDPR you have the right to:

- **access** your data: your account page offers a one-click **export** of everything we hold about
  you in a machine-readable JSON file;
- **rectify** it: edit your profile and settings yourself at any time;
- **erase** it: delete your account yourself (section 7), or ask us;
- **restrict** or **object** to processing based on legitimate interest or public interest;
- **withdraw consent** for the directory listing and email visibility at any time in your settings,
  without affecting the lawfulness of earlier processing;
- **data portability** of the data you provided, via the same export;
- **lodge a complaint** with a supervisory authority, in Greece the Hellenic Data Protection
  Authority (https://www.dpa.gr), or with the authority of your country of residence.

To exercise a right that the account page does not cover, write to louta@uowm.gr. We answer within
one month.

## 9. International transfers

Your data is stored in Greece. Cloudflare and Google may process limited data outside the European
Economic Area under the safeguards listed in section 5. No other transfers take place.

## 10. Children

The Platform is intended for professionals and stakeholders in flood management. Registration is
not open to persons under 16 **[CHECK: 15 under Greek Law 4624/2019, or 16]**. We do not knowingly
collect data from children; if you believe a child has registered, tell us and we will delete the
account.

## 11. Changes to this policy

We may update this policy to reflect changes in the Platform, the law or the project. The current
version and its date are always shown here; material changes are announced on the Platform and by
email to registered members.

## 12. Funding statement

The project is co-funded by the European Union through the Interreg IPA ADRION programme. This
Platform has been produced with the financial assistance of the European Union. Its content is the
sole responsibility of the University of Western Macedonia and can under no circumstances be
regarded as reflecting the position of the European Union and/or the IPA ADRION programme
authorities.

---

## Notes for the reviewer (not part of the policy)

- Everything stated here is implemented in the code as of 31 Oct 2026: argon2id hashing, hashed
  session tokens, HttpOnly/Secure/SameSite cookie, 30-day sliding sessions, 7-day cleanup of expired
  sessions and tokens, no IPs in the database, HMAC-hashed IPs in rate-limit logs, audit log without
  secrets, self-service export and anonymising deletion, directory and email visibility switches,
  no analytics. The 30-day purge of unverified accounts and the backup retention are scheduled for
  M4/M6 and must exist before go-live.
- Modelled on the IPA ADRION programme's own privacy policy (controller, legal bases, retention per
  data type, rights, named processors) and the structure of Interreg Euro-MED project notices.
- Open items: DPO naming; audit-log retention per the subsidy contract; hosting description;
  Cloudflare and Google DPAs on file; age threshold; Greek-language version.
