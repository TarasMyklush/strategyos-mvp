# Configuring organization and dimension structure

This guide is for the first Strategy Advisor setup. The advisor records the
client's reporting structure as data, reviews it with accountable owners, and asks
a separate tenant administrator to approve the version. The application does not
infer a complicated organization from uploaded files because legal entities,
management accountabilities and board reporting boundaries often differ.

## What belongs in each part

A **business unit** is an organizational accountability boundary. Create one when
an executive owns a distinct result, the unit is reviewed separately, or access
must be scoped separately. Use parent links to form the reporting hierarchy. Keep
stable keys when names change. Do not create a business unit merely because a
source system, product or customer has a different code.

A **dimension** is an analytical way to cut a measure, such as product, region,
channel or client. Dimensions are independent of the business-unit hierarchy.
Create a member hierarchy only when a parent total has a defined business meaning;
for example, `emea` may parent `gcc` and `europe`. Do not make a parent whose
children overlap. A cell is valid only when every configured dimension has one
known member.

A **source mapping** translates a registered source field and its raw values to
the stable configured keys. Map business-unit scope and every dimension. Preserve
the original source value in the evidence record. Unmapped, ambiguous or newly
observed values stop ingestion for review; they do not become `other`, zero, or a
guessed member.

## Rules of thumb

1. Start from the management accountability tree, then reconcile it to legal
   entities and source-system segments.
2. Keep organization and analytical dimensions separate. A regional subsidiary
   can be a business unit while region remains a dimension used across other units.
3. Use the smallest stable set needed to answer the board's recurring questions.
   Additive detail can arrive in a later approved version.
4. Give each key one meaning for its lifetime. Rename labels bilingually; never
   recycle a retired key for a different entity or member.
5. Require complete mapping for each configured dimension. Escalate one-to-many
   or context-dependent source values to the accountable owner.
6. Record source-system precedence when two systems provide the same property.
   Reconciliation rules belong in a later source contract, not in display labels.
7. Review access implications before approval. The structure describes scope but
   cannot grant source access or approval rights.
8. Save changes as consecutive immutable versions. Existing ratified plans retain
   their historical binding; new proposals use the current approved version.

## Worked example

Example Holdings reports a Group result with two accountable units: `distribution`
and `market-services`. Distribution has child units `north-operations` and
`south-operations`; Market Services is reviewed as one unit. Legal-entity codes do
not match this tree, so the advisor maps ERP segment `D-N` to `north-operations`,
`D-S` to `south-operations`, and `MS` to `market-services`.

The board reviews revenue by product, region and client type. The advisor therefore
configures three dimensions:

| Dimension | Members | Hierarchy |
| --- | --- | --- |
| Product | `core`, `specialty`, `services` | no overlap; each transaction has one |
| Region | `all-regions`, `north`, `south` | north and south roll to all-regions |
| Client type | `all-clients`, `retail`, `institutional` | retail and institutional roll to all-clients |

The ERP provides product and region, while the CRM owns client type. Both systems
are registered first. The configuration maps each raw field value to one stable
member. If CRM value `public-network` appears without an approved mapping, the
affected rows are held for review. The system does not assume it means
`institutional`.

The advisor previews the hierarchy and mappings with the Group CFO, saves version
1, and a separate tenant administrator approves it. A plan imported afterwards
must name version 1, its exact digest, a configured business-unit scope, and the
same dimension/member vocabulary. If version 2 is later approved, a pending plan
bound to version 1 becomes stale and cannot be ratified until it is reissued.

## Review checklist

- Every business unit has one accountable executive and at most one parent.
- Every dimension member is mutually exclusive at the level where measures enter.
- English and Arabic labels have been reviewed in the client's terminology.
- Every raw value in representative source extracts maps to one stable key.
- All source keys refer to registered systems; configuration does not broaden access.
- A second person has reviewed the hierarchy, mappings and business-unit scope.
- The approved digest is recorded in each new plan that uses the structure.
