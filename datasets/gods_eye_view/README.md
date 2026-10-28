# God's Eye View static-source snapshots

This directory contains immutable copies of the static source files used by
the Bhote Koshi historical reconstruction and the OpenInfraMap dams snapshot.
They let CI and deployed MASTERDB instances validate and ingest the documented
static datasets without requiring a sibling `gods-eye-view` checkout.

The connectors prefer an explicitly configured source location and then a
sibling development checkout. They use these files only when no checkout is
available. Provenance returned by the APIs continues to identify the original
God's Eye View paths and upstream attribution; these files are not runtime
observation or feature storage.
