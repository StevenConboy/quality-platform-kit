# AI resilience harness report

| | |
| --- | --- |
| Run at | {{run_at}} |
| Provider under test | {{provider}} |
| Groundedness judge | {{judge}} |
| Result | **{{result}}** |

{{summary_line}}

## Provider health

{{health_table}}

## Degradation

Each fault is injected and the app's response compared with the documented contract in
app/README.md. "Contract" is what the app promises; "Observed" is what it did.

{{degradation_table}}

## Adversarial

Payloads come from harness/payloads/adversarial.yaml. "Safe" means the app stayed in
control (200, valid single-line summary, checks held). "Rejected" means a clean 422.

{{adversarial_table}}

{{adversarial_failures}}

## Groundedness

Every summary produced during the run was checked against its ticket using the
**{{judge}}** method.

{{groundedness_table}}

{{groundedness_failures}}

## Token spend

{{quota_line}}

{{quota_table}}

{{judge_spend_line}}
