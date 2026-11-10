# Is Your Social Investment Paying Off?

Code and data for the case study **[Is Your Social Investment Paying Off? How to Measure What Reports Miss](https://measuredcallshq.github.io/social-traffic-conversion-case-study/)**, part of [Measured Calls](https://measuredcallshq.github.io/).

**Question.** Social brings 25% of the Google Merchandise Store's visits but 0.5% of its revenue. Should the business invest in social content to lift its sales, including purchases social prompts later through other channels?

**Findings**

- Social visits rarely buy: 0.05% include a purchase, 17 times below outside customers (0.77%, after separating Google's internal employee store).
- 94% of social visits come from YouTube, and most leave before viewing a product. Fixing that is worth at most about $5,500 a year.
- Later "discover on social, buy elsewhere" sales are largely invisible to cookie-based tracking, so they have to be tested, not measured.

**Recommendation.** A staged test plan, each test with its own decision: groundwork first; a low-cost landing-page A/B test judged on engagement and return visits; and, separately, a regional geo-lift test of a specific paid campaign, with its ad spend kept below what a big win would repay.

## Contents

| Path | What it is |
|---|---|
| `sql/merch-store-queries.sql` | BigQuery queries Q1–Q15 and Q17 on `bigquery-public-data.google_analytics_sample` (Q5, Q9 and Q15 retired; numbers kept to match the article) |
| `sql/q16-later-purchase-attribution.sql` | Q16: how later purchases by social-first visitors are credited (output `data/q16_later_purchase_attribution.csv`) |
| `data/` | Query outputs (`q1_…csv` to `q17_…csv`), so the Python and the notebook run without BigQuery |
| `analysis.py` | All calculations and the article's four charts |
| `geo_lift.py` | Marimo notebook for the regional (geo-lift) test in Stage 3: weekly orders by region, the noise model, simulated test sizes, spend caps, how to read a result and the check against the real weeks. Every Stage 3 figure in the appendix comes from it |
| `results.json` | Every number in the article |
| `img/` | Charts written by `analysis.py` |

## Reproduce

```bash
pip install -r requirements.txt
python3 analysis.py data .              # writes results.json and img/*.png
scripts/notebook.sh geo_lift.py           # opens the regional test notebook (or: marimo run geo_lift.py)
GEO_LIFT_AUTORUN=1 marimo export html geo_lift.py --no-include-code -o geo_lift.html -f   # rebuilds the static page linked from the appendix, with the button-gated chart pre-computed
```

To rebuild `data/` from scratch, run the queries in `sql/` in the free [BigQuery sandbox](https://cloud.google.com/bigquery/docs/sandbox) and save each result under the file name given in its comment (`-- Q1 -> q1_channel_monthly.csv`).

## Data

Google Analytics 360 sample for the Google Merchandise Store, Aug 2016 – Aug 2017 (903,653 sessions), published by Google as a BigQuery public dataset. Google obfuscates some fields and removes others; treat the figures as sample data, not audited sales. The data is nearly ten years old: the figures describe that store at that time, and the method is the point.
