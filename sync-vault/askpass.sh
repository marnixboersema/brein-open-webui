#!/bin/sh
# Called by git via GIT_ASKPASS to provide the GitHub PAT.
# Reading from a root-owned file (mode 600) keeps the token out of argv,
# process listings, the remote URL, and any log output on failure.
exec tr -d '\r\n' < /root/.brein-github-token
