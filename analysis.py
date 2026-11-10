"""Social-traffic conversion case study: analysis script.
Inputs (data/): query outputs q1-q16 from the BigQuery GA360 sample (sql/).
Run: python3 analysis.py <data_dir> <out_dir>
"""
import sys, math, json
import pandas as pd

D = sys.argv[1]; OUT = sys.argv[2]
R = {}

def phi(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def z_of(p):  # inverse normal, bisection
    lo, hi = -10, 10
    for _ in range(200):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if phi(m) < p else (lo, m)
    return (lo + hi) / 2

def n_per_arm(p, rel, alpha=0.05, power=0.8):
    p2 = p*(1+rel); za = z_of(1-alpha/2); zb = z_of(power)
    pb = (p+p2)/2
    return math.ceil((za*math.sqrt(2*pb*(1-pb)) + zb*math.sqrt(p*(1-p)+p2*(1-p2)))**2 / (p2-p)**2)

def binom_pmf(k, m, t): return math.comb(m, k) * t**k * (1-t)**(m-k)
def binom_cdf(k, m, t): return sum(binom_pmf(i, m, t) for i in range(k+1))
def _bisect(f):  # largest t in [0,1] with f(t) True, f monotone True->False
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo+hi)/2; lo, hi = (mid, hi) if f(mid) else (lo, mid)
    return (lo+hi)/2
def rate_ratio_test(a, n1, c, n2, alpha=0.05):
    """Rate ratio (a/n1)/(c/n2) with an exact CI and exact two-sided p (conditional binomial)."""
    m = a + c; ratio = (a/n1)/(c/n2)
    tl = 0.0 if a == 0 else _bisect(lambda t: 1 - binom_cdf(a-1, m, t) < alpha/2)
    th = 1.0 if a == m else _bisect(lambda t: binom_cdf(a, m, t) > alpha/2)
    odds = lambda t: (t/(1-t))*(n2/n1)
    t0 = n1/(n1+n2); pobs = binom_pmf(a, m, t0)
    p_exact = min(1.0, sum(binom_pmf(k, m, t0) for k in range(m+1) if binom_pmf(k, m, t0) <= pobs*(1+1e-9)))
    return dict(events=m, ratio=ratio, ci=[odds(tl), odds(th)], p_exact=p_exact)

# ---------- Part 1: Merch Store channel overview ----------
q1 = pd.read_csv(f"{D}/q1_channel_monthly.csv")
R["site_conv"] = q1.converting_sessions.sum()/q1.sessions.sum()

q3 = pd.read_csv(f"{D}/q3_funnel_by_channel.csv").set_index("channel")
f = pd.DataFrame({
  "view_rate": q3.viewed_product/q3.sessions,
  "cart_given_view": q3.added_to_cart/q3.viewed_product,
  "checkout_given_cart": q3.reached_checkout/q3.added_to_cart,
  "buy_given_checkout": q3.purchased/q3.reached_checkout,
  "conv": q3.purchased/q3.sessions})
R["funnel"] = f.loc[["Social","Organic Search","Direct"]].round(5).reset_index().to_dict("records")

q2 = pd.read_csv(f"{D}/q2_social_landing.csv")
src = q2.groupby("source")[["sessions","bounces","converting_sessions"]].sum().sort_values("sessions", ascending=False)
lp = q2.groupby("landing_section")[["sessions","bounces","converting_sessions"]].sum().sort_values("sessions", ascending=False)
lp["share"] = lp.sessions/lp.sessions.sum(); lp["bounce"] = lp.bounces/lp.sessions; lp["conv"]=lp.converting_sessions/lp.sessions
R["social_landing"] = lp.head(8).round(5).reset_index().to_dict("records")
nonyt = src.drop("youtube.com", errors="ignore")[["sessions","converting_sessions"]].sum()
R["youtube_vs_rest"] = dict(rest_sessions=int(nonyt.sessions), rest_conv=float(nonyt.converting_sessions/nonyt.sessions))

# social sources grouped (explicit map for the eight largest sources; everything else is "All other sources")
GROUPS = {"youtube.com":"YouTube", "m.facebook.com":"Facebook (3 domains)", "facebook.com":"Facebook (3 domains)",
          "l.facebook.com":"Facebook (3 domains)", "t.co":"Twitter (t.co)", "groups.google.com":"Google Groups",
          "reddit.com":"Reddit", "quora.com":"Quora"}
sg = src.assign(group=[GROUPS.get(i, "All other sources") for i in src.index]).groupby("group")[["sessions","bounces","converting_sessions"]].sum()
sg["share_sessions"] = sg.sessions/sg.sessions.sum(); sg["share_purchases"] = sg.converting_sessions/sg.converting_sessions.sum()
sg["conv"] = sg.converting_sessions/sg.sessions; sg["bounce"] = sg.bounces/sg.sessions
sg["conv_non_bounced"] = sg.converting_sessions/(sg.sessions - sg.bounces)  # a bounced session can't purchase
sg = sg.sort_values("sessions", ascending=False)
R["social_source_groups"] = sg.round(5).reset_index().to_dict("records")

# confounding check: landing page within source (YouTube vs the rest)
lbs = q2.assign(group=["YouTube" if x=="youtube.com" else "Non-YouTube" for x in q2.source]) \
        .groupby(["group","landing_section"])[["sessions","converting_sessions"]].sum()
lbs["conv"] = lbs.converting_sessions/lbs.sessions
lbs = lbs.loc[(slice(None), ["/home","/google+redesign"]), :]
R["landing_by_source"] = lbs.round(6).reset_index().to_dict("records")
pool = q2.groupby("landing_section")[["sessions","converting_sessions"]].sum().loc[["/home","/google+redesign"]]
pool["youtube_share"] = q2[q2.source=="youtube.com"].groupby("landing_section").sessions.sum().reindex(pool.index)/pool.sessions
R["landing_pooled"] = pool.assign(conv=pool.converting_sessions/pool.sessions).round(6).reset_index().to_dict("records")
# catalog vs home: exact CI and p-value
def _cat_home(df):
    cat, home = df.loc["/google+redesign"], df.loc["/home"]
    return rate_ratio_test(int(cat.converting_sessions), int(cat.sessions), int(home.converting_sessions), int(home.sessions))
R["landing_inference"] = {g: _cat_home(lbs.xs(g, level="group")) for g in ["YouTube", "Non-YouTube"]}
R["landing_inference"]["All social"] = _cat_home(pool)

# monthly social
soc_m = q1[q1.channel=="Social"].set_index("month")
R["social_monthly"] = soc_m[["sessions","converting_sessions"]].reset_index().to_dict("records")

# purchases on May 1-4, 2017, and the year-average and recent (Jun-Jul 2017) run rates (q4)
q4 = pd.read_csv(f"{D}/q4_daily_channel.csv"); q4["day"] = pd.to_datetime(q4.day)
sd = q4[q4.channel=="Social"].set_index("day")[["sessions","converting_sessions"]]
periods = []
for label, a, b in [("May 1-4, 2017", "2017-05-01", "2017-05-04")]:
    x = sd.loc[a:b]
    periods.append(dict(period=label, days=len(x), sessions=int(x.sessions.sum()), sessions_per_day=float(x.sessions.mean()),
                        converting_sessions=int(x.converting_sessions.sum()), conv=float(x.converting_sessions.sum()/x.sessions.sum())))
R["social_periods"] = periods
R["social_per_day_year"] = float(sd.loc[:"2017-07-31"].sessions.mean())
R["social_per_day_recent"] = float(sd.loc["2017-06-01":"2017-07-31"].sessions.mean())

# ---------- Part 2: experiment sizing ----------
# a test judged on social purchases: +50% at the recent (Jun-Jul 2017) social run rate
s = q3.loc["Social"]
p_buy = float(s.purchased/s.sessions); n_buy = n_per_arm(p_buy, 0.5)
R["sizes"] = dict(metric="social purchase conversion", baseline=p_buy, rel_lift=0.5, n_per_arm=n_buy,
                  days_at_recent=2*n_buy/R["social_per_day_recent"])

# scorecard: visits, purchases and revenue by social source (Q7, GA default attribution, same basis as Q1-Q2)
import os
if os.path.exists(f"{D}/q7_social_revenue_by_source.csv"):
    q7 = pd.read_csv(f"{D}/q7_social_revenue_by_source.csv")
    q7["group"] = [GROUPS.get(x, "All other sources") for x in q7.source]
    sc = q7.groupby("group")[["sessions","purchasing_sessions","transactions","revenue"]].sum()
    sc["share_sessions"] = sc.sessions/sc.sessions.sum()
    sc["share_purchases"] = sc.purchasing_sessions/sc.purchasing_sessions.sum()
    sc["share_revenue"] = sc.revenue/sc.revenue.sum()
    sc = sc.sort_values("sessions", ascending=False)
    tot = sc[["sessions","purchasing_sessions","transactions","revenue"]].sum()
    sc.loc["All social"] = tot
    for c, col in [("share_sessions","sessions"),("share_purchases","purchasing_sessions"),("share_revenue","revenue")]:
        sc.loc["All social", c] = tot[col]/tot[col]
    sc["conversion"] = sc.purchasing_sessions/sc.sessions
    sc["revenue_per_purchasing_session"] = sc.revenue/sc.purchasing_sessions
    sc["revenue_per_visit"] = sc.revenue/sc.sessions
    R["scorecard"] = dict(rows=sc.round(6).reset_index().to_dict("records"))
# channel revenue (Q13), social funnel by audience (Q10), sizing by audience and test sizes
if os.path.exists(f"{D}/q13_channel_revenue_referral_split.csv"):
    q13 = pd.read_csv(f"{D}/q13_channel_revenue_referral_split.csv").set_index("channel")
    q13["share_sessions"] = q13.sessions/q13.sessions.sum(); q13["share_revenue"] = q13.revenue/q13.revenue.sum()
    q13["conversion"] = q13.purchasing_sessions/q13.sessions; q13["revenue_per_visit"] = q13.revenue/q13.sessions
    R["channel_revenue"] = q13.round(6).reset_index().to_dict("records")
    # store averages without Google's internal store (employees buying via mall.googleplex.com etc.)
    ext = q13.drop(["Referral (Google internal sites)"])
    R["store_external"] = dict(sessions=int(ext.sessions.sum()), purchasing_sessions=int(ext.purchasing_sessions.sum()),
        revenue=float(ext.revenue.sum()), conversion=float(ext.purchasing_sessions.sum()/ext.sessions.sum()),
        revenue_per_visit=float(ext.revenue.sum()/ext.sessions.sum()))
if os.path.exists(f"{D}/q10_social_funnel_by_audience.csv"):
    q10 = pd.read_csv(f"{D}/q10_social_funnel_by_audience.csv").set_index("audience")
    q10["view_rate"] = q10.viewed_product/q10.sessions
    q10["buy_given_view"] = q10.purchasing_sessions/q10.viewed_product
    q10["revenue_per_purchase"] = q10.revenue/q10.purchasing_sessions
    R["social_funnel_by_audience"] = q10.round(6).reset_index().to_dict("records")
    search_view = float(f.loc["Organic Search","view_rate"])
    sz = []
    # scenarios quoted in the article: YouTube at 1.5x and at search's view rate; Facebook and Google Groups at search's
    for aud, scen in [("YouTube", ("1.5x view rate", "search's view rate")), ("Facebook and Google Groups", ("search's view rate",))]:
        r = q10.loc[aud]
        for label, vr in [("1.5x view rate", 1.5*r.view_rate), ("search's view rate", search_view)]:
            if label not in scen or vr <= r.view_rate: continue
            extra_buyers = (vr - r.view_rate)*r.sessions*r.buy_given_view
            sz.append(dict(audience=aud, scenario=label, view_rate=vr, extra_purchases=extra_buyers,
                           extra_revenue=extra_buyers*r.revenue_per_purchase))
    R["sizing_by_audience"] = sz
    def weeks(p, rel, visits_per_year):
        nn = n_per_arm(p, rel); return dict(baseline=p, rel_lift=rel, n_per_group=nn, weeks=2*nn/(visits_per_year/52.14))
    fg = q10.loc["Facebook and Google Groups"]
    R["test_sizes"] = dict(
        buying_purchase=[weeks(fg.purchasing_sessions/fg.sessions, r, fg.sessions) for r in (0.5, 1.0)],
        buying_view=[weeks(fg.view_rate, 0.5, fg.sessions)])
def log_rr(a, n1, c, n2):
    """Rate ratio with a normal 95% interval on the log scale (for large counts)."""
    r = (a/n1)/(c/n2); se = math.sqrt(1/a - 1/n1 + 1/c - 1/n2)
    z = (math.log(r))/se
    return dict(ratio=r, ci=[r*math.exp(-1.96*se), r*math.exp(1.96*se)], p_two=2*(1-phi(abs(z))))
# social-first visitors: does a product view on the first visit go with coming back and buying later? (Q11)
if os.path.exists(f"{D}/q11_social_first_view_later.csv"):
    q11 = pd.read_csv(f"{D}/q11_social_first_view_later.csv")
    out = {}
    for aud, g11 in q11.groupby("audience"):
        v_, n_ = g11[g11.viewed_product_first_visit].iloc[0], g11[~g11.viewed_product_first_visit].iloc[0]
        out[aud] = dict(
            viewed=dict(visitors=int(v_.visitors), return_rate=v_.returned/v_.visitors, later_buy_rate=v_.bought_later/v_.visitors, later_revenue=float(v_.later_revenue)),
            not_viewed=dict(visitors=int(n_.visitors), return_rate=n_.returned/n_.visitors, later_buy_rate=n_.bought_later/n_.visitors, later_revenue=float(n_.later_revenue)),
            return_ratio=log_rr(int(v_.returned), int(v_.visitors), int(n_.returned), int(n_.visitors)),
            later_buy_ratio=rate_ratio_test(int(v_.bought_later), int(v_.visitors), int(n_.bought_later), int(n_.visitors)))
    out["totals"] = dict(visitors=int(q11.visitors.sum()), returned=int(q11.returned.sum()),
                         bought_later_not_first=int(q11.bought_later_not_first.sum()), later_revenue=float(q11.later_revenue.sum()))
    R["social_first_view_later"] = out
# Stage 2 sizing for YouTube: product-view test at YouTube's own baseline, and how far return
# visits could move. Upper bound: assumes the whole observed viewer/non-viewer return gap is causal.
if "social_funnel_by_audience" in R and "social_first_view_later" in R:
    yt = next(r for r in R["social_funnel_by_audience"] if r["audience"] == "YouTube")
    v0 = yt["view_rate"]; n_view = n_per_arm(v0, 0.5)
    fv = R["social_first_view_later"]["YouTube"]
    r_v, r_n = fv["viewed"]["return_rate"], fv["not_viewed"]["return_rate"]
    base = v0*r_v + (1-v0)*r_n
    rows = []
    for v1 in (v0*1.5, 0.05, 0.10, 0.164):
        new_r = v1*r_v + (1-v1)*r_n
        rows.append(dict(view_rate=v1, return_base=base, return_new=new_r, rel_lift=new_r/base-1,
                         n_per_group=n_per_arm(base, new_r/base-1)))
    wk_recent = lambda n: 2*n/R["social_per_day_recent"]/7   # weeks, both groups, at Jun-Jul 2017 social traffic
    for r_ in rows: r_["weeks_at_recent"] = wk_recent(r_["n_per_group"])
    # sizing the return-visit test to settle it either way: smallest rise worth acting on, fixed in advance
    settle = [dict(base=base, rel_lift=rl, n_per_group=n_per_arm(base, rl), weeks_at_recent=wk_recent(n_per_arm(base, rl)))
              for rl in (0.30, 0.20, 0.15)]
    settle.append(dict(base=0.025, rel_lift=0.20, n_per_group=n_per_arm(0.025, 0.20),
                       weeks_at_recent=wk_recent(n_per_arm(0.025, 0.20)), note="if the 90-day return rate is 2.5%"))
    R["stage2_youtube"] = dict(view_baseline=v0, view_n_per_group_50pct=n_view,
        view_weeks_at_recent_social=wk_recent(n_view), return_base=base, return_sensitivity=rows, return_test_sizes=settle)

# time from first social visit to the first later purchase (Q14: social-first visitors who didn't buy on the first visit)
if os.path.exists(f"{D}/q14_social_first_days_to_later_purchase.csv"):
    q14 = pd.read_csv(f"{D}/q14_social_first_days_to_later_purchase.csv")
    bins = [("under 1 day", 0, 1), ("1-7 days", 1, 8), ("8-30 days", 8, 31), ("31-90 days", 31, 91), ("over 90 days", 91, 1e9)]
    cnt = [int(((q14.days_to_later_purchase >= a) & (q14.days_to_later_purchase < b)).sum()) for _, a, b in bins]
    cum = pd.Series(cnt).cumsum()/len(q14)
    R["time_to_later_purchase"] = dict(buyers=len(q14), median_days=float(q14.days_to_later_purchase.median()),
        max_days=float(q14.days_to_later_purchase.max()),
        bins=[dict(bin=l, buyers=c, cumulative=float(cu)) for (l, _, _), c, cu in zip(bins, cnt, cum)])

# how later purchases by social-first visitors are credited under GA's default attribution (Q16)
if os.path.exists(f"{D}/q16_later_purchase_attribution.csv"):
    q16 = pd.read_csv(f"{D}/q16_later_purchase_attribution.csv")
    soc16 = q16[q16.channel == "Social"]; oth16 = q16[q16.channel != "Social"]
    R["later_purchase_attribution"] = dict(
        buyers=int(q16.buyers.sum()), revenue=float(q16.revenue.sum()),
        credited_to_social=dict(buyers=int(soc16.buyers.sum()), revenue=float(soc16.revenue.sum())),
        credited_elsewhere=dict(buyers=int(oth16.buyers.sum()), revenue=float(oth16.revenue.sum())),
        arrived_through_social_link=int(q16[(q16.channel == "Social") & ~q16.true_direct].buyers.sum()))

# headline figures derived from the results above (quoted in the article)
cr = {r["channel"]: r for r in R["channel_revenue"]}
soc = cr["Social"]; ext = R["store_external"]
mon = pd.DataFrame(R["social_monthly"]).set_index("month")
yt_sg = next(r for r in R["social_source_groups"] if r["group"] == "YouTube")
fb_sg = next(r for r in R["social_source_groups"] if r["group"].startswith("Facebook"))
best = [r for r in R["sizing_by_audience"] if r["scenario"] == "search's view rate"]
sv, ov = f.loc["Social"], f.loc["Organic Search"]
recent_share = R["social_per_day_recent"]/R["social_per_day_year"]
R["derived"] = dict(
    social_conv_gap_vs_external=ext["conversion"]/soc["conversion"],
    social_conv_gap_vs_store=R["site_conv"]/soc["conversion"],
    view_step_share_of_gap_vs_search=math.log(sv.view_rate/ov.view_rate)/math.log(sv.conv/ov.conv),
    youtube_vs_facebook_non_bounced_conv=fb_sg["conv_non_bounced"]/yt_sg["conv_non_bounced"],
    social_non_bounced_conv=sg.converting_sessions.sum()/(sg.sessions.sum()-sg.bounces.sum()),
    monthly_peak=int(mon.sessions.max()), june_2017=int(mon.loc["2017-06","sessions"]),
    fall_from_peak_to_june=1-mon.loc["2017-06","sessions"]/mon.sessions.max(),
    may_2017_share_of_purchases=mon.loc["2017-05","converting_sessions"]/mon.converting_sessions.sum(),
    recent_share_of_year_traffic=recent_share,
    best_case_extra_revenue=sum(r["extra_revenue"] for r in best),
    best_case_share_of_revenue=sum(r["extra_revenue"] for r in best)/sum(r["revenue"] for r in R["channel_revenue"]),
    best_case_share_of_external=sum(r["extra_revenue"] for r in best)/ext["revenue"],
    best_case_at_recent_traffic=sum(r["extra_revenue"] for r in best)*recent_share,
    first_time_social_return_rate=R["social_first_view_later"]["totals"]["returned"]/R["social_first_view_later"]["totals"]["visitors"])
json.dump(R, open(f"{OUT}/results.json","w"), indent=1, default=str)

# ---------- Charts ----------
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"font.size":11, "axes.spines.top":False, "axes.spines.right":False})
BLUE, GREY, ORANGE = "#2a6fdb", "#9aa3ad", "#e07a1f"

# 1 channels: share of visits, conversion, share of revenue (Q13)
c = pd.read_csv(f"{D}/q13_channel_revenue_referral_split.csv").set_index("channel")
c = c[c.sessions>1000]
c = c.rename(index={"Referral (Google internal sites)":"Referral: Google internal", "Referral (other sites)":"Referral: other sites"})
c["share"] = c.sessions/c.sessions.sum(); c["conv"] = c.purchasing_sessions/c.sessions; c["rev_share"] = c.revenue/c.revenue.sum()
c = c.sort_values("sessions")
cols = [ORANGE if i=="Social" else GREY for i in c.index]
fig, axs = plt.subplots(1, 3, figsize=(11,4.4), sharey=True, layout="constrained")
panels = [(c.share*100, "1. Share of visits", "% of all visits", lambda v: f"{v:.1f}%", 60),
          (c.conv*100, "2. Share of visits that buy", "% of visits with a purchase", lambda v: f"{v:.2f}%", 7),
          (c.rev_share*100, "3. Share of revenue", "% of all revenue", lambda v: (f"{v:.1f}%" if v>=1 else f"{v:.2f}%"), 60)]
si = list(c.index).index("Social")
for ax,(vals,title,xl,fmt,xmax) in zip(axs, panels):
    ax.axhspan(si-0.45, si+0.45, color=ORANGE, alpha=0.10, lw=0)
    ax.barh(c.index, vals, color=cols, height=0.62)
    floor = R["store_external"]["conversion"]*100 if title.startswith("2.") else 0
    for k,v in enumerate(vals):
        ax.text(max(v, floor)+xmax*0.03, k, fmt(v), va="center", fontsize=9.5, fontweight="bold" if c.index[k]=="Social" else "normal")
    ax.set_xlim(0, xmax*1.25); ax.set_title(title, loc="left", fontsize=11); ax.set_xlabel(xl)
ext_conv = R["store_external"]["conversion"]*100
axs[1].axvline(ext_conv, color="black", ls="--", lw=1)
axs[1].text(ext_conv+0.1, -0.45, "store average excl. Google internal %.2f%%" % ext_conv, fontsize=8.5, va="center")
for ax in axs[1:]: ax.tick_params(axis="y", left=False)
fig.suptitle("Social brings a quarter of visits but under 1% of purchases and revenue", x=0.01, ha="left", fontsize=12)
fig.savefig(f"{OUT}/img/01-conversion-by-channel.png", dpi=160)

# 2 funnel step rates social vs organic vs direct
steps = ["view_rate","cart_given_view","checkout_given_cart","buy_given_checkout"]
labels = ["Viewed a product\n(of all visitors)","Added to cart\n(of those who viewed)","Started checkout\n(of carts)","Purchased\n(of checkouts)"]
fig, ax = plt.subplots(figsize=(7.5,3.8)); w=0.27
for k,(chn,col) in enumerate([("Social",ORANGE),("Organic Search",GREY),("Direct","#5b6670")]):
    vals = [f.loc[chn,s]*100 for s in steps]
    ax.bar([i+(k-1)*w for i in range(4)], vals, w, label={"Organic Search":"Search"}.get(chn, chn), color=col)
ax.set_xticks(range(4)); ax.set_xticklabels(labels, fontsize=9); ax.set_ylabel("%"); ax.legend(frameon=False, fontsize=9)
ax.set_title("Most social visitors leave before viewing a product", loc="left", fontsize=12)
fig.tight_layout(); fig.savefig(f"{OUT}/img/02-funnel-steps.png", dpi=160)

# 2b social sources: share of social sessions vs share of social purchases, and conversion rate
g = sg.sort_values("sessions")
yy = list(range(len(g)))
fig, (a1, a2) = plt.subplots(1, 2, figsize=(10,4.6), sharey=True, layout="constrained")
a1.barh([y+0.19 for y in yy], g.share_sessions*100, height=0.36, color=GREY, label="share of social visits")
a1.barh([y-0.19 for y in yy], g.share_purchases*100, height=0.36, color=BLUE, label="share of social purchases")
for y,s_,p_ in zip(yy, g.share_sessions*100, g.share_purchases*100):
    a1.text(s_+1, y+0.19, f"{s_:.1f}%", va="center", fontsize=8.5, color="#555")
    a1.text(p_+1, y-0.19, f"{p_:.1f}%", va="center", fontsize=8.5, color=BLUE)
a1.set_yticks(yy); a1.set_yticklabels(g.index)
a1.set_xlim(0, 110); a1.set_xlabel("% of all social visits / of all social purchases")
a1.legend(frameon=False, fontsize=8.5, loc="lower right")
a1.set_title("1. Visits vs purchases", loc="left", fontsize=11)
a2.barh(yy, g.conv*100, height=0.55, color=[ORANGE if i=="YouTube" else GREY for i in g.index])
for y,v,n,m in zip(yy, g.conv*100, g.converting_sessions, g.sessions):
    a2.text(4.45, y, (f"{v:.3f}%" if v<0.1 else f"{v:.2f}%"), va="center", fontsize=10, fontweight="bold" if g.index[y]=="YouTube" else "normal")
    a2.text(6.5, y, f"{n:,} / {m:,}", va="center", fontsize=8.5, color="#555")
a2.text(4.45, len(g)-0.45, "conversion", fontsize=9, color="#555", va="bottom"); a2.text(6.5, len(g)-0.45, "purchases / visits", fontsize=9, color="#555", va="bottom")
a2.axvline(1.42, color="black", ls="--", lw=1); a2.text(1.47, -0.72, "benchmark 1.42%", fontsize=8.5, va="center")
all_soc = sg.converting_sessions.sum()/sg.sessions.sum()*100
a2.axvline(all_soc, color=ORANGE, ls=":", lw=1.5)
a2.text(1.47, -0.45, "all social %.3f%% (dotted)" % all_soc, fontsize=8.5, va="center", color=ORANGE)
a2.set_xlim(0, 10.2); a1.set_ylim(-0.95, len(g)+0.05); a2.set_xlabel("Visits with a purchase (%)")
a2.set_title("2. How many of them buy", loc="left", fontsize=11); a2.tick_params(axis="y", left=False)
fig.suptitle("Two small sources (Facebook, Google Groups) bring three-quarters of social purchases", x=0.01, ha="left", fontsize=12)
fig.savefig(f"{OUT}/img/02b-social-sources.png", dpi=160)

# 5 social monthly: visits and purchasing visits
fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.5,4.6), sharex=True, layout="constrained")
soc_m = soc_m.drop("2017-08", errors="ignore")  # data ends 1 Aug 2017: one day, leave it out
mlab = [pd.Period(m, "M").strftime("%b %y") for m in soc_m.index]
xs = range(len(soc_m))
a1.bar(xs, soc_m.sessions/1000, color=GREY); a1.set_ylabel("Visits (k)")
a1.set_title("1. Social visits per month", loc="left", fontsize=11)
pc = [ORANGE if m == "2017-05" else BLUE for m in soc_m.index]
a2.bar(xs, soc_m.converting_sessions, color=pc); a2.set_ylabel("Purchasing visits")
for x, v in zip(xs, soc_m.converting_sessions): a2.text(x, v+0.8, str(int(v)), ha="center", fontsize=8.5)
a2.set_ylim(0, soc_m.converting_sessions.max()*1.25)
a2.set_title("2. Social purchasing visits per month (May 2017 highlighted)", loc="left", fontsize=11)
a2.set_xticks(list(xs)); a2.set_xticklabels(mlab, fontsize=8.5)
fig.suptitle("Social visits fell 95% from their November peak; a third of the year's purchases came in May", x=0.01, ha="left", fontsize=11.5)
fig.savefig(f"{OUT}/img/05-social-monthly.png", dpi=160)
print("done")
