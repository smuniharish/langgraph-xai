# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x | Yes: security fixes are released as 1.x patch versions |
| 0.1.x | No: upgrade to 1.x |

Fixes are made on the latest 1.x release. Unreleased development code receives
fixes before release.

## Reporting a vulnerability

Please report suspected vulnerabilities privately to
samamuniharish@gmail.com. Include a clear description, affected versions,
reproduction steps, potential impact, and any suggested mitigation. Do not
include credentials or sensitive production data.

We will acknowledge a report, assess impact, and coordinate disclosure with the
reporter when possible. Please do not publish details until a fix or mitigation
is available.

## Explainability data guidance

Explainability artifacts can contain sensitive application context. Deployers
are responsible for:

- selecting conservative capture settings;
- applying disclosure policy at capture, storage, export, and display;
- configuring retention, access control, and encryption for chosen storage and
  external services;
- keeping API keys and connection strings outside source control; and
- reviewing integrations' own security and data-handling terms.

`langgraph-xai` is not designed to collect private model chain-of-thought.
Do not rely on explanation artifacts as a substitute for authorization,
auditing, incident response, or security controls.

## Security changes

Contributors should document security-relevant capture, retention, export, and
failure-mode changes, and add focused tests where practical.
