# Versioning and updates

Stable releases use `MAJOR.MINOR.PATCH`; previews use `MAJOR.MINOR-betaN`. Ordering compares major and minor numerically, ranks stable above preview within the same minor, then compares patch or beta number. Legacy `MAJOR.MINOR.PATCH-betaN` is accepted only for installed historical versions.

Checks run about 15 seconds after activation and every six hours thereafter, reading stable and preview feeds. All newer valid releases install automatically, including major upgrades and switches between preview and stable. Both feeds participate in version ordering; the newest valid release wins. No automatic downgrade is performed.

There are no update popups. Status, errors, install controls and restart instructions appear inline in Memory. Mandatory host-owned permissions or installation UI remain under DSH control. Failed checks preserve the installed version. A manual check button remains available.

GitHub is currently the only configured source. Inactive preview metadata means no preview is offered. Downloads use fixed trusted sources and filenames rather than client-supplied URLs or paths. Preflight verifies metadata, size, SHA-256, package identity, version, bundle declaration and archive paths. Build IDs derive from release source contents. Installation receipts persist, and uncertain results are not automatically resubmitted.

DSH owns installation and activation. Use its plugin manager if the remote interface is unavailable. A successful installation is not evidence of model-quality verification.
