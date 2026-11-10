-- Q16 -> q16_later_purchase_attribution.csv : later purchases by social-first visitors, split by how
-- Google Analytics' default attribution credits them. channel = GA's channelGrouping for the purchasing
-- session; true_direct = the visitor typed the address (GA still credits these to the earlier source).
-- Result (run 30 Oct 2026): 33 buyers, $3,769; 21 buyers / $3,362 credited to Social (20 of them typed-in
-- returns), 12 buyers / $407 to other channels.
WITH s AS (
 SELECT fullVisitorId v, visitNumber n, visitStartTime t, channelGrouping ch,
  IFNULL(trafficSource.isTrueDirect,false) td, IFNULL(totals.transactions,0) tx,
  IFNULL(totals.totalTransactionRevenue,0)/1e6 rev
 FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`),
f AS (SELECT v, t FROM s WHERE n=1 AND ch='Social'),
later AS (SELECT s.* FROM s JOIN f USING(v) WHERE s.t>f.t AND s.tx>0)
SELECT ch AS channel, td AS true_direct, COUNT(DISTINCT v) AS buyers, COUNT(*) AS sessions, ROUND(SUM(rev), 2) AS revenue
FROM later GROUP BY 1,2 ORDER BY 3 DESC, 1, 2;
