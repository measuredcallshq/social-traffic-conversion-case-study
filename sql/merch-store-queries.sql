-- Google Merchandise Store (GA360 sample, Aug 2016 – Aug 2017)
-- Run each query separately in BigQuery; save each result as CSV with the name shown.

-- Q1 -> q1_channel_monthly.csv : sessions, bounces and purchases by channel and month
SELECT
  FORMAT_DATE('%Y-%m', PARSE_DATE('%Y%m%d', date)) AS month,
  channelGrouping AS channel,
  SUM(totals.visits) AS sessions,
  SUM(IFNULL(totals.bounces, 0)) AS bounces,
  SUM(IFNULL(totals.transactions, 0)) AS transactions,
  COUNTIF(IFNULL(totals.transactions, 0) > 0) AS converting_sessions
FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
GROUP BY month, channel
ORDER BY month, channel;

-- Q2 -> q2_social_landing.csv : social sessions by landing section, device and source
SELECT
  IFNULL(REGEXP_EXTRACT(lp, r'^(/[^/?]*)'), '(none)') AS landing_section,
  device.deviceCategory AS device,
  trafficSource.source AS source,
  COUNT(*) AS sessions,
  SUM(IFNULL(totals.bounces, 0)) AS bounces,
  COUNTIF(IFNULL(totals.transactions, 0) > 0) AS converting_sessions
FROM (
  SELECT *,
    (SELECT h.page.pagePath FROM UNNEST(hits) h WHERE h.isEntrance = TRUE LIMIT 1) AS lp
  FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
  WHERE channelGrouping = 'Social'
)
GROUP BY landing_section, device, source
ORDER BY sessions DESC;

-- Q3 -> q3_funnel_by_channel.csv : how far sessions get in the shopping funnel
SELECT
  channelGrouping AS channel,
  COUNT(*) AS sessions,
  COUNTIF(EXISTS(SELECT 1 FROM UNNEST(hits) h WHERE h.eCommerceAction.action_type = '2')) AS viewed_product,
  COUNTIF(EXISTS(SELECT 1 FROM UNNEST(hits) h WHERE h.eCommerceAction.action_type = '3')) AS added_to_cart,
  COUNTIF(EXISTS(SELECT 1 FROM UNNEST(hits) h WHERE h.eCommerceAction.action_type = '5')) AS reached_checkout,
  COUNTIF(IFNULL(totals.transactions, 0) > 0) AS purchased
FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
GROUP BY channel
ORDER BY sessions DESC;

-- Q4 -> q4_daily_channel.csv : daily series, used to look for changes over time
SELECT
  PARSE_DATE('%Y%m%d', date) AS day,
  channelGrouping AS channel,
  SUM(totals.visits) AS sessions,
  COUNTIF(IFNULL(totals.transactions, 0) > 0) AS converting_sessions
FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
GROUP BY day, channel
ORDER BY day, channel;

-- Q6 -> q6_first_channel_journeys.csv : do first-time visitors buy later, and through which channel?
-- One row per (first channel, returned?, first-purchase channel, days to purchase); a few hundred rows.
-- Only visitors whose first session in the data is their first visit ever (visitNumber = 1).
-- "Direct (true)" uses trafficSource.isTrueDirect: GA otherwise labels a returning direct visit
-- with the visitor's previous campaign source, so later direct purchases would look like Social.
WITH s AS (
  SELECT
    fullVisitorId,
    visitStartTime,
    visitNumber,
    IF(trafficSource.isTrueDirect, 'Direct (true)', channelGrouping) AS channel,
    IFNULL(totals.transactions, 0) > 0 AS purchased
  FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
),
v AS (
  SELECT fullVisitorId,
         ARRAY_AGG(STRUCT(visitStartTime, visitNumber, channel, purchased) ORDER BY visitStartTime) AS ss
  FROM s
  GROUP BY fullVisitorId
),
f AS (
  SELECT
    ss[OFFSET(0)].channel AS first_channel,
    ss[OFFSET(0)].visitNumber AS first_visit_number,
    ss[OFFSET(0)].purchased AS bought_first_session,
    ss[OFFSET(0)].visitStartTime AS t0,
    ARRAY_LENGTH(ss) > 1 AS returned,
    (SELECT AS STRUCT x.channel, x.visitStartTime FROM UNNEST(ss) x WHERE x.purchased ORDER BY x.visitStartTime LIMIT 1) AS fp
  FROM v
)
SELECT
  first_channel,
  returned,
  CASE WHEN fp IS NULL THEN '(no purchase)'
       WHEN bought_first_session THEN '(first session)'
       ELSE fp.channel END AS first_purchase_channel,
  CASE WHEN fp IS NULL THEN NULL
       WHEN bought_first_session THEN '0'
       WHEN fp.visitStartTime - t0 < 7*86400 THEN '1-7 days'
       WHEN fp.visitStartTime - t0 < 30*86400 THEN '8-30 days'
       ELSE '31+ days' END AS days_to_purchase,
  COUNT(*) AS visitors
FROM f
WHERE first_visit_number = 1
GROUP BY 1, 2, 3, 4
ORDER BY first_channel, visitors DESC;

-- Q7 -> q7_social_revenue_by_source.csv : purchases and revenue by social source
-- Revenue is stored in micros (divide by 1e6) and is obfuscated by Google: realistic in pattern, not exact.
-- Uses GA's default attribution, like Q1-Q2: a returning direct visit keeps the earlier social source,
-- so purchasing sessions total 104, matching the rest of the article.
SELECT
  trafficSource.source AS source,
  COUNT(*) AS sessions,
  COUNTIF(totals.transactions > 0) AS purchasing_sessions,
  SUM(IFNULL(totals.transactions, 0)) AS transactions,
  ROUND(SUM(IFNULL(totals.totalTransactionRevenue, 0)) / 1e6, 2) AS revenue
FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
WHERE channelGrouping = 'Social'
GROUP BY source
ORDER BY sessions DESC;

-- Q8 -> q8_social_medium_campaign.csv : is the social traffic organic or paid?
-- Every social session has medium "referral" and campaign "(not set)": no campaign-tagged or paid social.
SELECT
  trafficSource.source AS source,
  trafficSource.medium AS medium,
  trafficSource.campaign AS campaign,
  COUNT(*) AS sessions
FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
WHERE channelGrouping = 'Social'
GROUP BY source, medium, campaign
ORDER BY sessions DESC;

-- Q10 -> q10_social_funnel_by_audience.csv : social funnel and revenue by audience (YouTube vs buying communities)
SELECT
  CASE WHEN trafficSource.source = 'youtube.com' THEN 'YouTube'
       WHEN trafficSource.source IN ('facebook.com','m.facebook.com','l.facebook.com','groups.google.com') THEN 'Facebook and Google Groups'
       ELSE 'Other social' END AS audience,
  COUNT(*) AS sessions,
  COUNTIF(EXISTS(SELECT 1 FROM UNNEST(hits) h WHERE h.eCommerceAction.action_type = '2')) AS viewed_product,
  COUNTIF(EXISTS(SELECT 1 FROM UNNEST(hits) h WHERE h.eCommerceAction.action_type = '3')) AS added_to_cart,
  COUNTIF(EXISTS(SELECT 1 FROM UNNEST(hits) h WHERE h.eCommerceAction.action_type = '5')) AS reached_checkout,
  COUNTIF(IFNULL(totals.transactions, 0) > 0) AS purchasing_sessions,
  ROUND(SUM(IFNULL(totals.totalTransactionRevenue, 0)) / 1e6, 2) AS revenue
FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
WHERE channelGrouping = 'Social'
GROUP BY audience
ORDER BY sessions DESC;

-- Q11 -> q11_social_first_view_later.csv : do social-first visitors who view a product come back and buy later?
-- First-time visitors (visitNumber = 1) whose first visit came from social, split by whether that first visit
-- included a product view. Later visits are linked by cookie (fullVisitorId), so returns on another device are missed.
WITH s AS (
  SELECT fullVisitorId, visitStartTime, visitNumber, channelGrouping AS channel,
         trafficSource.source AS source,
         IFNULL(trafficSource.isTrueDirect, FALSE) AS true_direct,
         IFNULL(totals.transactions, 0) > 0 AS purchased,
         IFNULL(totals.totalTransactionRevenue, 0) / 1e6 AS revenue,
         EXISTS(SELECT 1 FROM UNNEST(hits) h WHERE h.eCommerceAction.action_type = '2') AS viewed_product
  FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
),
v AS (SELECT fullVisitorId, ARRAY_AGG(s ORDER BY visitStartTime) AS ss FROM s GROUP BY fullVisitorId),
f AS (
  SELECT ss[OFFSET(0)] AS first, ARRAY_LENGTH(ss) > 1 AS returned,
    (SELECT COUNTIF(x.purchased) FROM UNNEST(ss) x WITH OFFSET o WHERE o > 0) > 0 AS bought_later,
    (SELECT SUM(x.revenue) FROM UNNEST(ss) x WITH OFFSET o WHERE o > 0) AS later_revenue
  FROM v
)
SELECT
  IF(first.source = 'youtube.com', 'YouTube', 'Other social') AS audience,
  first.viewed_product AS viewed_product_first_visit,
  COUNT(*) AS visitors,
  COUNTIF(first.purchased) AS bought_first_visit,
  COUNTIF(returned) AS returned,
  COUNTIF(bought_later) AS bought_later,
  COUNTIF(bought_later AND NOT first.purchased) AS bought_later_not_first,
  ROUND(SUM(IFNULL(later_revenue, 0)), 2) AS later_revenue
FROM f
WHERE first.visitNumber = 1 AND first.channel = 'Social' AND NOT first.true_direct
GROUP BY audience, viewed_product_first_visit
ORDER BY audience, viewed_product_first_visit;

-- Q12 -> q12_referral_internal_referrers.csv : where do Referral visits recorded with source "(direct)" come from?
-- trafficSource.source shows "(direct)", but every one has a referral path; the first hit's referrer
-- (hits.referer) shows Google's internal sites, mainly mall.googleplex.com. Top 8 rows saved.
SELECT
  (SELECT h.referer FROM UNNEST(hits) h WHERE h.hitNumber = 1) AS first_hit_referer,
  COUNT(*) AS sessions,
  ROUND(SUM(IFNULL(totals.totalTransactionRevenue, 0)) / 1e6, 0) AS revenue
FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
WHERE channelGrouping = 'Referral' AND trafficSource.source = '(direct)'
GROUP BY first_hit_referer
ORDER BY sessions DESC
LIMIT 8;

-- Q13 -> q13_channel_revenue_referral_split.csv : visits, purchases and revenue by channel, with Referral split into Google internal sites and other sites (Figure 1)
-- (Q5, Q9 and Q15 were earlier drafts and have been removed; query numbers are kept so the article's references stay valid.)
SELECT
  CASE WHEN channelGrouping = 'Referral' AND trafficSource.source = '(direct)' THEN 'Referral (Google internal sites)'
       WHEN channelGrouping = 'Referral' THEN 'Referral (other sites)'
       ELSE channelGrouping END AS channel,
  COUNT(*) AS sessions,
  COUNTIF(IFNULL(totals.transactions, 0) > 0) AS purchasing_sessions,
  SUM(IFNULL(totals.transactions, 0)) AS transactions,
  ROUND(SUM(IFNULL(totals.totalTransactionRevenue, 0)) / 1e6, 2) AS revenue
FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
GROUP BY channel
ORDER BY sessions DESC;

-- Q14 -> q14_social_first_days_to_later_purchase.csv : days from the first social visit to the first later purchase
-- Social-first visitors (as in Q11) who didn't buy on the first visit but bought on a later one: 32 rows.
WITH s AS (
  SELECT fullVisitorId, visitStartTime, visitNumber, channelGrouping AS channel,
         trafficSource.source AS source,
         IFNULL(trafficSource.isTrueDirect, FALSE) AS true_direct,
         IFNULL(totals.transactions, 0) > 0 AS purchased
  FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
),
v AS (SELECT fullVisitorId, ARRAY_AGG(s ORDER BY visitStartTime) AS ss FROM s GROUP BY fullVisitorId),
f AS (
  SELECT ss[OFFSET(0)] AS first,
    (SELECT MIN(x.visitStartTime) FROM UNNEST(ss) x WITH OFFSET o WHERE o > 0 AND x.purchased) AS first_later_buy
  FROM v
)
SELECT
  IF(first.source = 'youtube.com', 'YouTube', 'Other social') AS audience,
  ROUND((first_later_buy - first.visitStartTime) / 86400, 1) AS days_to_later_purchase
FROM f
WHERE first.visitNumber = 1 AND first.channel = 'Social' AND NOT first.true_direct
  AND NOT first.purchased AND first_later_buy IS NOT NULL
ORDER BY days_to_later_purchase;

-- Q17 -> q17_geo_lift_panel.csv : weekly orders, revenue and buyers by country and metro, for sizing the regional test (Stage 3, geo_lift.py)
-- Weekly orders, revenue and buyers by country and metro, outside customers only.
-- Outside customers = everything except Google's internal store:
--   not (channelGrouping = 'Referral' AND source = '(direct)').
-- Weeks start Monday 2016-08-01 (week 0); weeks 0..51 are kept.
-- Location is GA's estimate from the visitor's IP address (no shipping address in this dataset).
SELECT
  DIV(DATE_DIFF(PARSE_DATE('%Y%m%d', date), DATE '2016-08-01', DAY), 7) AS wk,
  geoNetwork.country AS country,
  geoNetwork.metro AS metro,
  SUM(totals.transactions) AS orders,
  SUM(totals.totalTransactionRevenue) / 1e6 AS revenue,
  COUNT(DISTINCT fullVisitorId) AS buyers
FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
WHERE totals.transactions > 0
  AND NOT (channelGrouping = 'Referral' AND trafficSource.source = '(direct)')
GROUP BY 1, 2, 3
HAVING wk BETWEEN 0 AND 51;
