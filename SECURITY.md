# Security Policy

SARAPH takes the security of ARIA and its users seriously. This document explains
how to report a vulnerability and what to expect in return.

## Reporting a vulnerability

If you believe you have found a security vulnerability in ARIA, please report it
privately. **Do not open a public issue for security problems.**

- Email: **litesaraph@gmail.com**
- Include: a description of the issue, the steps to reproduce it, the potential
  impact, and any proof-of-concept you have. Please give us a reasonable window
  to investigate and fix before any public disclosure.

We ask that you:

- Do not access, modify, or delete data that is not yours.
- Do not run attacks that degrade the service for others (for example DoS).
- Act in good faith and avoid privacy violations.

Researchers who report in good faith and follow this policy will not be pursued
for their testing.

## What to expect

- **Acknowledgement** of your report as soon as we can review it.
- An assessment of severity and a plan to remediate genuine issues.
- Credit for the report if you would like it, once a fix is released.

## Scope

In scope:

- The ARIA web application (`aria-ai.fly.dev`) and its API.
- This repository's source code.

Out of scope:

- Third-party services ARIA integrates with (report those to the respective
  vendor): Google, GitHub, Stripe, and connected publishing platforms.
- Findings that require physical access, social engineering of SARAPH staff, or
  already-disclosed issues.

## Handling secrets

If you discover exposed credentials (API keys, tokens, secrets) in the codebase,
commit history, logs, or screenshots, treat them as sensitive: report them
privately and do not use them. Do not paste live secrets into issues, pull
requests, or commits.

## Our commitments

ARIA's security and compliance posture — including the frameworks we are working
toward (SOC 2, ISO/IEC 27001) and where we are not yet compliant (HIPAA) — is
described honestly on our public [Trust Center](https://aria-ai.fly.dev/trust).
