# Independent evaluation intake

`edge_cases.csv` is synthetic regression coverage. It must never be described
as an independent evaluation set and must not be mixed with this folder.

This folder holds a **local-only**, human-reviewed evaluation set. Its records
are ignored by Git because an offer, complaint, or email can contain personal
data. Keep only redacted text: remove candidate names, contact details, payment
identifiers, addresses, and attachments before saving it.

## Intake rules

1. Freeze a batch before changing any detection rule or score weight.
2. Use public sources or material for which the contributor has permission.
3. Require two reviewers to agree on `truth`; otherwise exclude the case.
4. Put every near-duplicate and every case from one publisher in the same
   `source_group`. A source group must be entirely in development or entirely
   in evaluation.
5. Record source, collection date, and review evidence in the local manifest.
   A complaint alone is not proof that an employer or sender is fraudulent.
6. Run the frozen batch only after the rules are locked. Report counts of
   dangerous misses, false alarms, and abstentions; do not claim accuracy from
   a small or source-biased sample.

## Local manifest

Copy `template.csv` to `cases.csv` and place each redacted text file under
`cases/`. Both locations are ignored by Git.

- `case_id`: stable local identifier, such as `EXT-001`.
- `split`: `development` or `evaluation`. Never tune rules against `evaluation`.
- `source_group`: source/publisher/collection group used to prevent leakage.
- `truth`: `scam` or `legitimate`, after two-person review.
- `source_url`: public origin or an internal consent record reference.
- `collected_at`: ISO-8601 date.
- `reviewed_by`: reviewer initials only.
- `text_file`: redacted file path relative to this folder.

The template has no cases and is safe to commit. It is an intake contract, not
evidence that the project has an independent benchmark yet.
