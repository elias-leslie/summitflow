# Native deployment observations

`st service observe PROJECT --task ID --acceptance RECEIPT --evidence JSON`
verifies a deployment managed by its owner and writes a reference usable by
`st done --evidence JSON`. It does not deploy or restart services.

The backend resolves the task's registered project and one granted
`observe_deployment` executable extension. It validates full current source
acceptance, executes the observer from those immutable Git objects with a fresh
challenge, and stores the resulting receipt outside development checkouts.
Clients may request observations and reference receipts; they cannot submit
authoritative observations or override the target, executable or source rule.
Trusted owner registration selects the verifier. Removing client type markers
or disabling a registration cannot downgrade native verification to legacy;
unreadable or malformed relevant registration blocks required completion gates.

The public SDK's `st_sdk.native_deployment` module defines version 1 requests
and responses. Owners verify package signatures, original build identity,
installed/running artifacts and live behavior. A valid failed observation exits
zero and reports failed checks. Transport failures exit nonzero. ST retains
failed attempts without their raw output or private stderr; failures never
satisfy completion gates.
Failed observations may retain an unknown deployed identity; successful
observations require a full build commit and the runtime source proof.

ST computes a runtime projection from every Git tree entry's path, mode, type
and object identity. The owner supplies a versioned tracked policy file with
reviewed nonruntime exclusions; its immutable contents must exactly match the
response. The deployed commit must be an ancestor of the accepted commit and
both projections must match. The receipt retains both revisions, the policy
digest, changed paths and observer code identity. Equality of runtime inputs
does not claim identical rebuilt binaries: the original embedded build commit
and observed artifact hashes remain the deployment identity.

Each completion gate reloads the server's private immutable receipt and checks
the submitted descriptors exactly, bound to task, project, acceptance ID and
accepted revision. A copied receipt or a caller's verified flag cannot satisfy
the gate. Receipt timestamps describe when the observations occurred; requesting
observation always runs fresh checks. There is no invented expiry policy.

This trust model separates ordinary API clients from the service account that
owns receipts. Compromise of that operating-system account or an administrator
is outside the receipt's trust model. Existing managed deployment phases and
exact-source checks remain unchanged.
