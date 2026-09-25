# Optional IB newsletter profile

Recorded 2026-09-08 at the user's explicit request. Future product requirement only; no collection fields, subscriptions, mailing integration or messages implemented by this note.

## User intent

Retain an email address and a small student profile, including grade/year level, to tailor useful IB newsletters. Keep this separate from essential account/service communications.

## Proposed minimal profile

- Newsletter email: default to the account email only after the user chooses to subscribe; permit a separately verified preferred address.
- Grade/year level: student-confirmed; retain its school/year-system meaning rather than assuming Grade 11 universally means DP1.
- IB programme and stage: for example MYP, DP or CP, with programme year where applicable. Allow unknown/not applicable.
- Expected graduation year, optional: useful for cohort timing without collecting date of birth; do not infer exact age from school grade.
- Selected topics, optional: study strategies, subject resources, assessments, CAS, TOK, extended essay and IB updates, where relevant to their programme.
- Preferred language and frequency, optional.
- Subject interests, optional and student-selected; not academic performance or a transcript.

## Boundaries and lifecycle

- Separate, explicit newsletter opt-in; never preselected or required for school connection. Login/enrollment is not newsletter consent.
- Account email already used for authentication is not automatically a mailing-list subscription. Verify ownership before enabling delivery, especially for an alternative address.
- Record subscription state and the time/version/source of opt-in. Provide preference editing, unsubscribe and deletion/retention handling; retain only the minimum suppression data needed to honor opt-outs.
- Do not silently reuse grades, task content, submissions, teacher comments, private messages, inferred struggles or other school records for marketing/personalization.
- If programme/year is suggested from ManageBac, explain that use and have the student confirm it. Avoid silent background profile enrichment.
- Keep newsletter data and permissions logically separate from authentication credentials and academic caches; never share passwords, session cookies or OAuth tokens with an email provider.
- Review age-appropriate consent, school restrictions and applicable requirements before launch. No legal compliance conclusion is made in this planning note.
- Update year/stage through occasional confirmation; avoid indefinite retention of a stale school-year profile.

## Open decisions

Newsletter provider, sending frequency, editorial scope, retention period, consent/age handling and whether an IB newsletter belongs in initial onboarding or a later optional preferences screen. Prefer offering it after essential connection setup so it does not add friction.
