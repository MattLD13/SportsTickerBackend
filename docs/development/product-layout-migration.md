# Product layout migration

The product layout uses named product folders while preserving Python package names.
The showcase keeps its page sources, assets, and rendered examples.
Generated source provenance records the relocated files and updated build tool.

## Six preparation release

`run.py` configures product imports from `release-layout.json` before starting a product.
The updater reads target package paths from the same manifest before compilation.
The controller service uses the stable root launcher.
The unchanged package layout remains declared in the preparation commit.

The updater and launcher own release layout selection. Fixed package paths no longer own it.
Tests validate both declared layouts and reject paths outside the target release.
The initial focused updater, update journal, and frame-health run passed 11 tests.

Deploy the preparation commit to existing Six devices before deploying the product-folder commit.
Older updaters cannot validate a release with relocated packages.
Do not publish the entire branch directly to production before this device migration.

The backend archives retain their existing runtime package paths.
Source package paths and archive package paths have separate explicit owners.
