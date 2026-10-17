# Aviva — demo script

## Configuration tested

- Routing: `claude-haiku-4-5-20251001` (`ROUTING_MODEL_NAME` in config.py)
- SQL generation, fix step, answer formatting: `claude-sonnet-5-5`
- Streamlit skips the Tableau filter-extraction call
- Ground truth computed independently from the CSVs with pandas, not by the pipeline

## Timing per question (end to end, from the pipeline call)

| | Routing call (median) | Total (median) | Total (mean) | Slowest |
|---|---|---|---|---|
| Before: Sonnet routing + filter extraction | 1.52s | 8.09s | 9.11s | 14.86s |
| After: Haiku routing, no filter extraction | 0.94s | **4.02s** | 4.25s | 6.55s |

"Before" is 10 runs (1 per question); "after" is 30 runs (3 per question).
Most of the saving comes from dropping the filter call (one fewer Sonnet round trip).
Haiku saves about 0.6s on routing and also has much less variance (0.80–1.24s vs 1.10–5.00s).

## The 10 questions

| # | Question | Correct source | Sonnet route | Haiku route (3 runs) | Correct? | Ground truth |
|---|---|---|---|---|---|---|
| 1 | Who is the top performing sales rep? | sales_data | sales_data | sales_data ×3 | 3/3 | Sarah Chen, $12,320.30 |
| 2 | What were total sales in the West region? | sales_data | sales_data | sales_data ×3 | 3/3 | $5,349.02 |
| 3 | How much did Priya Patel sell in total? | sales_data | sales_data | sales_data ×3 | 3/3 | $11,596.12 |
| 4 | Which marketing channel had the best ROI? | marketing_data | marketing_data | marketing_data ×3 | 3/3 | Email, ROI 36.56 |
| 5 | How many conversions did our LinkedIn campaigns drive? | marketing_data | marketing_data | marketing_data ×3 | 3/3 | 399 |
| 6 | **How much revenue did our Instagram ads generate?** | **marketing_data** | **facebook_ads** | **facebook_ads ×3** | **0/3** | $77,000 |
| 7 | Which Facebook campaign had the best ROAS? | facebook_ads | facebook_ads | facebook_ads ×3 | 3/3 | Retargeting - Cart Abandoners, 13.10 |
| 8 | Which ad placement had the lowest cost per click? | facebook_ads | facebook_ads | facebook_ads ×3 | 3/3 | Feed, $0.43 |
| 9 | Which Amazon product had the most customer returns? | vendor_central | vendor_central | vendor_central ×3 | 3/3 | ActiveFoam Roller, 161 |
| 10 | Which product category drove the most ordered revenue on Amazon? | vendor_central | vendor_central | vendor_central ×3 | 3/3 | Nutrition, $551,773.95 |

Haiku and Sonnet routed all 10 questions identically, so routing stays on Haiku.
No run needed a self-correction retry.

## The 4 demo questions (all 3/3 correct, all four sources)

1. **Which marketing channel had the best ROI?** → Marketing.
   ROI isn't a column; Claude derives it as (revenue − spend) / spend. Answer: Email.
2. **Which Facebook campaign had the best ROAS?** → Facebook Ads.
   Same idea, a derived ratio. Answer: Retargeting - Cart Abandoners, 13.1.
3. **Which Amazon product had the most customer returns?** → Amazon Vendor Central.
   Answer: ActiveFoam Roller, 161.
4. **Who is the top performing sales rep?** → Sales. Answer: Sarah Chen, $12,320.30.
   Good one to repeat with the **"simulate a bad first query"** toggle on, to show self-correction.

Note: all 4 return a single row, so no chart appears. If you want a chart on camera,
"What were total sales by region?" was run twice during Step 5 (both correct: Northeast
$12,344.45 … West $5,349.02, total $33,773.70) but it wasn't part of this 10-question run.

## The misroute: "How much revenue did our Instagram ads generate?"

**What happens:** it routes to `facebook_ads` every time (Sonnet 1/1, Haiku 3/3). That table
has no Instagram breakdown: its `placement` values are Feed, Stories, Reels and
Audience Network. So the SQL filters on `placement ILIKE '%instagram%'`, gets nothing, and the
answer says it couldn't find an Instagram revenue figure. The correct answer is **$77,000**,
from `marketing_data` where `channel = 'Instagram'`.

**Why, from the source descriptions in config.py:**

- `facebook_ads` says it *is* Instagram data, twice: it opens with *"Facebook and Instagram
  paid advertising data"* and its routing hints include *"Use this source for questions about
  Facebook ads, Meta ads, Instagram ads, …"*. The question says "Instagram ads", so this
  is an almost exact phrase match.
- `marketing_data` only mentions Instagram as one value in a parenthetical list:
  *"channel (Google Ads, Facebook, Instagram, LinkedIn, Email)"*. Nothing tells the router
  that this is where Instagram totals live.
- The router only sees the descriptions, not the data. The description promises Instagram
  ads, but the actual columns can't separate Instagram from Facebook.

**What to point at on camera:** the routing box shows the router's own reason, *"This table
contains Instagram paid advertising data…"* (it's repeating the description), and the
**runner-up is `marketing_data`**, the correct table.

**The fix (not applied):** make the descriptions match the data. Either remove "Instagram ads"
from the `facebook_ads` hints, or add "Does not break out Instagram separately; use
marketing_data for Instagram channel totals". This is a data-catalog problem, not a model problem.
