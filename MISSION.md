# Mission

## What I want to be able to do

Stand up SUBAY on a fresh Ubuntu 26.04 laptop and drive Slice 15
(production hardening) all the way to a signed-off, patient-data-ready box - then
"fully commit" the slice: land the last artifact in git and merge the HITL branch
to `master` once sign-off is real.

## Why it matters

SUBAY is the single system-of-record for a CMV kidney-transplant study. It holds
Personal Information under RA 10173. Slice 15 is the difference between a box that
*runs* and a box that is *safe to hold patient data*. Until the RUNBOOK sign-off
table is signed, the laptop is not cleared. Getting this wrong on the real box
(auto-reboot into a locked disk, un-decryptable backups, secrets in git) is the
actual risk - not clever attackers.

## How I'll know I'm getting better

- I can explain the 4-phase deploy path and what each CHECKLIST section (§1-§8) buys.
- I complete each phase's Verify check before moving on, and stop when one fails.
- I understand why slice-15 is a HITL branch and is not merged AFK.
- The RUNBOOK sign-off table is complete and the branch is merged to `master`.

## Constraints

- Fresh laptop, Ubuntu 26.04 LTS Desktop, beginner at the command line.
- One operator; localhost-only box in Davao (SPMC-sited in the real study).
- De-identification and LUKS are hard legal requirements, not niceties.
