# Project Memory Schema

The shared memory is the agent's long-term state. In phases 1–4 it can be a spreadsheet with one tab per record type. Later it can become a database.

## Rules for every record
- `id`, `created`, `updated`, `source` (file, meeting or link) are required.
- `status` separates drafts from facts: `PROPOSED` (agent draft) → `APPROVED` (a person confirmed it) → `SUPERSEDED`.
- The agent may create `PROPOSED` records only. Only a named person can set `APPROVED`, and the record keeps `approved_by` and `approved_on`.
- Never overwrite an approved record. Create a new one and mark the old one `SUPERSEDED`.
- `access` holds the project or group allowed to see the record, such as NDA vendor material.

## Record types

### Submission (from the Innovation Hub intake form)
| id | title | description | current_process | people_affected | frequency | impact | desired_outcome | suggested_solution | department | submitted_by | created_at | status: Submitted / Needs clarification / Under review / Accepted / Declined |

An accepted Submission becomes a Project.

### AgentRun (one row per agent call, for traceability and evals)
| id | workflow | input_ids | prompt_version | model | started_at | finished_at | output_json | status | reviewed_by | review_outcome: Approved / Edited / Rejected |

### Project
| Field | Example |
|---|---|
| id | PRJ-007 |
| name | Robotic inspection — Hall B |
| stage | Idea / Evaluating / Pilot design / Pilot running / Decision / Scaling / Stopped |
| business_problem | Manual thermal rounds take 6 h per shift `[Khazna-tested]` |
| sponsor | name or UNASSIGNED |
| requirements | links to Requirement records |

### Requirement
| Field | Example |
|---|---|
| id, project_id | REQ-031, PRJ-007 |
| text | Operates in hot aisles at 35 °C or above |
| priority | Must / Should |
| status | PROPOSED / APPROVED |

### Vendor
| id | name | products | contacts | nda_in_place | access |

### Evidence
One row per claim. This record powers the evidence labels.
| Field | Example |
|---|---|
| id, subject (vendor/product), project_id | EV-112 |
| claim | Battery lasts 8 h on continuous patrol |
| label | Vendor-stated / Independent / Khazna-tested / Assumption / Unknown |
| source | Proposal v2, p.4 |
| contradicts | EV-098 (if any) |

### Decision
| id | project_id | decision | agreed_by | date | source | status |

### Action
| id | project_id | action | owner (or UNASSIGNED) | due (or NO DATE AGREED) | state: New / In progress / Done / Overdue | source |

### Pilot
| id | project_id | baseline | success_criteria | start | end | results | outcome: Scale / Extend / Revise / Stop / Inconclusive |

## How the three first workflows use memory
- **Meeting notes →** create `PROPOSED` Decision and Action records, and Evidence records for vendor claims.
- **Vendor documents →** create Evidence records, then compare against the project's approved Requirements.
- **Weekly report →** read only `APPROVED` records, plus `PROPOSED` ones clearly marked as pending.
