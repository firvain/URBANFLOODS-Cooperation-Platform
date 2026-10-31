# Accessibility Statement — URBANFLOODS Cooperation Platform

**Version 1 (draft for review), 31 October 2026.** This is the text the platform's
`/accessibility` page will show (increment 5e). It follows the model accessibility statement of
Commission Implementing Decision (EU) 2018/1523. Items marked **[CHECK]** need confirmation by the
University of Western Macedonia before go-live; the conformance status must be revisited when the
accessibility pass (5d) is closed.

---

## 1. Our commitment

The **University of Western Macedonia (UOWM)**, Lead Partner of the project URBANFLOODS
(IPA-ADRION00374), is committed to making the URBANFLOODS Cooperation Platform accessible, in
accordance with Directive (EU) 2016/2102 on the accessibility of the websites and mobile
applications of public sector bodies, transposed into Greek law by Law 4727/2020.

This statement applies to https://cooperation.urbanfloods.app. It does not cover the URBANFLOODS
KNOWBASE (https://knowbase.urbanfloods.app), which is a separate application with its own
statement, nor external websites we link to.

## 2. Compliance status

This website is **partially conformant** with the Web Content Accessibility Guidelines
(WCAG) 2.1, level AA, and with the harmonised European standard EN 301 549, because of the
non-conformities listed in section 3. **[CHECK after 5d: change to "fully conformant" only if the
accessibility audit closes every item in section 3.1]**

## 3. Non-accessible content

The content listed below is not yet fully accessible, for the following reasons.

### 3.1 Non-conformities with WCAG 2.1 level AA

The colour-contrast, avatar-initials and link-name issues found in the first self-assessment were
corrected on 31 October 2026 (text and button colours, placeholders, the focus indicator and the
email link name now meet the required ratios on every page that was scanned). The hover state of
solid green, amber, olive and blue buttons (for example "Approve" in the moderation queue), where
the white label fell just below 4.5:1, was also corrected on 31 October 2026: these buttons now
darken on hover and press instead of lightening.

No non-conformities with WCAG 2.1 level AA are currently known.

### 3.2 Content outside the scope of the applicable legislation or under the author's control

- **Images uploaded by members.** The editor requires a text alternative for every image, but we
  cannot verify that each description written by a member is accurate and sufficient.
- **Content written by members.** Posts, threads, replies and comments are written by members. We
  provide headings, lists and links in the editor, but the structure and clarity of each
  contribution depend on its author.
- **KNOWBASE content.** Measures, documents and other items from the URBANFLOODS KNOWBASE are shown
  as received from that separate application. Documents it links to (for example PDF files)
  are third-party content and may not be accessible.
- **Bot check.** The registration and password forms use Cloudflare Turnstile, a third-party
  service. In most cases it runs without any interaction; when it asks for one, its
  accessibility depends on Cloudflare. **[CHECK: whether an alternative registration route (by
  email to the contact below) should be offered]**

## 4. What we have done

The Platform was designed and built with accessibility as a requirement. In particular:

- every page can be used with the keyboard alone, with a visible focus indicator;
- a "skip to main content" link is the first element on every page;
- when you move to another page, the keyboard focus moves to the page heading and the new page
  title is announced to screen readers;
- pages use semantic landmarks (header, navigation, main content, footer) and a logical heading
  order;
- every form field has a visible label, and error messages are linked to their fields and
  announced;
- status messages (for example "saved" or "sending") are announced through live regions;
- the rich-text editor toolbar uses real buttons with accessible names and pressed states, and
  images cannot be inserted without a text alternative;
- animations and transitions are switched off when your system asks for reduced motion;
- content written by members is cleaned of unsafe or disruptive markup before it is shown;
- text can be resized up to 200% and the layout adapts to small screens without horizontal
  scrolling of the page **[CHECK after 5d: confirm in the audit]**;
- the interface is available in nine languages, and each page declares its language.

## 5. Preparation of this accessibility statement

This statement was prepared on **31 October 2026**.

The method used is a **self-assessment** by the development team: automated checks of the public
pages with axe-core against the WCAG 2.1 level A and AA rules, run in the Platform's automated
end-to-end tests (Playwright), complemented by manual keyboard checks. **[CHECK after 5d: list the
pages covered by the final audit and the date it was completed]**

The statement was last reviewed on 31 October 2026.

## 6. Feedback and contact information

If you find a barrier on the Platform, need information in an accessible format, or want to report
content that does not meet the requirements, please contact:

Prof. Malamati Louta, Scientific Coordinator of URBANFLOODS, University of Western Macedonia,
louta@uowm.gr.

Please describe the page (its address), the problem, and, if possible, the browser and assistive
technology you use. We will reply within **10 working days**. **[CHECK: response period agreed by
UOWM]**

## 7. Enforcement procedure

If you are not satisfied with our reply to your feedback or to your request for accessible
information, you may turn to the body responsible in Greece for the enforcement procedure under
Law 4727/2020: the **Greek Ombudsman** (Synigoros tou Politi), https://www.synigoros.gr.
**[CHECK: confirm the enforcement body named in Law 4727/2020 and whether the Ministry of Digital
Governance, as monitoring body, should also be listed]**

## 8. Compatibility with browsers and assistive technology

The Platform is designed to work with the current and previous major versions of Firefox, Chrome,
Edge and Safari, on desktop and mobile. It is designed to be compatible with screen readers and
other assistive technology that support WAI-ARIA. **[CHECK: which screen readers and browsers were
tested manually, e.g. NVDA with Firefox, VoiceOver with Safari]**

## 9. Technical specifications

The accessibility of the Platform relies on the following technologies, which work with the
combination of web browser and assistive technology installed on your computer:

- HTML
- WAI-ARIA
- CSS
- JavaScript

The Platform requires JavaScript to be enabled.

---

## Notes for the reviewer (not part of the statement)

- Section 3.1 is taken from the axe findings recorded in PROGRESS.md during M1–M3 (contrast on
  /partners, /about, /register placeholders; avatar initials on posts and threads; mailto label
  mismatch). No full audit has been run yet; the accessibility pass (5d) is still to do. After 5d,
  update sections 2, 3.1 and 5 with what the audit actually found and fixed. Do not claim full
  conformance without a passing audit.
- Section 4 lists only what exists in the code as of 31 Oct 2026: SkipLink, focus on the h1 after
  route change with an aria-live announcement, labelled UFormField fields, role="alert" and
  aria-live messages, prefers-reduced-motion CSS, DOMPurify rendering (SafeHtml), required alt
  text in the image upload dialog, eslint-plugin-vuejs-accessibility in lint.
- The "200% resize / reflow" claim (section 4) must be confirmed by the 5d audit.
- Open items: conformance status; response period; enforcement body; screen readers tested;
  alternative to the Turnstile check; Greek-language version.
