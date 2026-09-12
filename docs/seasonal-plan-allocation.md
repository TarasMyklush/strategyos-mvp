# Seasonal plan allocation

The approved parent target remains in the Intent Vault. A seasonal profile proposes a different distribution of that target; it cannot change the total or approve itself.

1. Register the evidence file containing the seasonal factors through source intake. Record its source-pack identifier, file name and SHA-256. A seasonal factor is a planning input, not an actual result.
2. In the selected ratified plan, choose the parent cell, split dimension and a completed prior actual snapshot. Load the historical mix.
3. Enable **Apply a separately evidenced seasonal profile**. Enter the registered seasonal source information, then a factor and exact row/cell reference for every proposed child. Enter each accountable owner and any separate planning adjustment.
4. Review the resulting proposal and its lineage. A separately authorized executive must ratify the new version. A newer ratified parent makes the proposal stale.

For each child, the engine computes:

`effective weight = historical value × seasonal factor × (1 + planning adjustment percent / 100)`

It allocates the approved parent target in proportion to those effective weights. Decimal arithmetic preserves the total exactly; the final cell in lexicographic order receives the disclosed rounding remainder.

For example, historical weights 40 and 60 with seasonal factors 2 and 1 and no further adjustment produce weights 80 and 60. An approved target of 100 becomes 57.14 and 42.86 at two decimal places. This is an illustrative calculation, not a customer result.

Factors must be positive decimal strings and no greater than 1,000. Missing factors or evidence are rejected; they are never silently treated as 1. The unchanged factor 1 must be supplied explicitly when a seasonal profile is enabled. Missing or nonpositive history blocks allocation.

Source permission changes or changed evidence bytes block further use. The plan's **Technical detail** panel offers separate historical and seasonal evidence links. Board exports include the allocation basis, unit-labelled values, factor references and the full immutable derivation in their provenance register. Sector terminology and seasonal assumptions belong in the client configuration and evidence file, never in the engine.
