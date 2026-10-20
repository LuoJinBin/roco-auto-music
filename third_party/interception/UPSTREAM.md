# Optional Interception dependency

Official project: https://github.com/oblitum/Interception

Release: https://github.com/oblitum/Interception/releases/tag/v1.0.1

Library source: https://github.com/oblitum/Interception/tree/v1.0.1/library

The repository does not redistribute the upstream DLL, driver or installer.
`tools/fetch_interception.py` retrieves the official archive only on explicit
invocation, checks its hash and extracts the x64 DLL. It never installs or
executes the downloaded files. The application dynamically loads that library
by absolute path only after verifying its hash.

- Archive SHA-256: `ad038963d6413055765128b0b931f6e765147c9916dba79e65d872b261f9af10`
- x64 DLL SHA-256: `ab88164c11b1b48488772d4c3bfaa4509d5b0ae9dbc5a691dc4f96f0260443c8`

The upstream README distinguishes non-commercial LGPL library use from
commercial licensing. The supplied LGPL v3 text and upstream terms are
independent of this project's MIT license. See THIRD_PARTY_NOTICES.md at the
repository root for details. This project grants no third-party commercial
license.
