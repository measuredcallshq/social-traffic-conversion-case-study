import marimo

__generated_with = "0.17.6"
app = marimo.App(width="medium", app_title="Geo-lift test")


@app.cell
def _():
    import math
    import os
    from pathlib import Path

    import altair as alt
    import marimo as mo
    import numpy as np
    import pandas as pd
    from scipy.optimize import nnls
    from scipy.stats import norm

    AUTORUN = os.environ.get("GEO_LIFT_AUTORUN") == "1"  # run the button-gated cells without clicking (testing)
    return AUTORUN, Path, alt, math, mo, nnls, norm, np, os, pd


@app.cell
def _(mo):
    mo.md(r"""
    # Sizing a geo-lift test of paid social

    Every number behind the geo-lift test plan, derived step by step from the Merchandise Store's weekly orders by region.
    Sections 1 to 4 explore the data and need no test decisions; each set of controls sits right above the sections
    that use it.
    """)
    return


@app.cell
def _(mo, phi, rho, sigma):
    mo.md(f"""
    | Section | Derives |
    |---|---|
    | 0. Data | Weekly orders, revenue and buyers by region, live from BigQuery |
    | 1. Regions in scope | Which regions count, and which are left out |
    | 2. What the data shows | Orders a week, sales a year, sales a day per group |
    | 3. Chance and clumping | Poisson check; clumping (≈ {phi:.1f}) |
    | 4. Regional swing | A region's own swing (≈ {sigma:.0%}) and its persistence (≈ {rho:.2f}), with ranges |
    | 5. Regions and split | Fake-region sizes, the size cap, pairing and coin flip |
    | 5b. Detectable lift and spend cap | Smallest detectable lift by length (with 95% ranges), and the most ad spend that breaks even at it |
    | 6. Reading the chosen test | The bar for a real lift, outcomes by true lift, and how to read a result |
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 0. Data: live from BigQuery
    """)
    return


@app.cell
def _(mo, os):
    bq_project = mo.ui.text(
        value=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        label="Google Cloud project (billing)",
        full_width=True,
    )
    bq_run = mo.ui.run_button(label="Query BigQuery")
    bq_force = mo.ui.checkbox(value=False, label="Force a fresh query even if this query is cached")
    mo.vstack(
        [
            mo.md(
                "The query reads the public `bigquery-public-data.google_analytics_sample` dataset and is billed "
                "to your project (well within BigQuery's free monthly allowance). Without a project, the notebook loads the saved "
                "extract `data/q17_geo_lift_panel.csv`. Results are cached in "
                "`.cache/`, under a name made from the query text: the same query is never run twice, and "
                "editing the query fetches fresh data. Moving controls never re-runs the query. "
                "Sign in once in a terminal: `gcloud auth application-default login`."
            ),
            bq_project,
            mo.hstack([bq_run, bq_force], justify="start"),
        ]
    )
    return bq_force, bq_project, bq_run


@app.cell
def _():
    SQL = r"""
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
    HAVING wk BETWEEN 0 AND 51
    """
    return (SQL,)


@app.cell
def _(Path, SQL, bq_force, bq_project, bq_run, mo, os, pd):
    import hashlib

    _dir = Path(str(mo.notebook_dir() or "."))
    _key = hashlib.sha1(" ".join(SQL.split()).encode()).hexdigest()[:10]  # ignores whitespace-only edits
    CACHE = _dir / ".cache" / f"geo_lift_panel_{_key}.csv"
    _override = os.environ.get("GEO_LIFT_PANEL_CSV")  # a saved extract, for offline runs
    if _override:
        raw = pd.read_csv(_override)
        bq_note = f"Loaded {_override}."
    elif CACHE.exists() and not bq_force.value:
        raw = pd.read_csv(CACHE)
        bq_note = f"Loaded the cache for this query ({CACHE.name}); no BigQuery query run."
        if bq_run.value:
            bq_note += " Tick *Force a fresh query* to re-query."
    elif (_dir / "data" / "q17_geo_lift_panel.csv").exists() and not bq_run.value:
        raw = pd.read_csv(_dir / "data" / "q17_geo_lift_panel.csv")
        bq_note = "Loaded the saved extract `data/q17_geo_lift_panel.csv` (Q17); no BigQuery query run. Press *Query BigQuery* to re-query."
    elif bq_run.value:
        mo.stop(not bq_project.value.strip(), mo.md("**Enter a Google Cloud project first.**"))
        from google.cloud import bigquery

        _client = bigquery.Client(project=bq_project.value.strip())
        _job = _client.query(SQL)
        raw = _job.to_dataframe()
        CACHE.parent.mkdir(exist_ok=True)
        raw.to_csv(CACHE, index=False)
        bq_note = f"Queried BigQuery: {(_job.total_bytes_processed or 0) / 1e9:.2f} GB read; saved {CACHE.name}."
    else:
        mo.stop(
            True,
            mo.md(
                "**No cached data for this query.** Enter your project and press *Query BigQuery*."
                + (" (Force is on: press the button to re-query.)" if CACHE.exists() else "")
            ),
        )
    mo.md(f"{bq_note} {len(raw):,} rows (week × country × metro).")
    return (raw,)


@app.cell
def _(mo):
    metro_min = mo.ui.number(start=0, stop=1000, step=10, value=40, label="Orders a year to count as its own metro")
    seed = mo.ui.number(start=0, stop=10_000, step=1, value=7, label="Random seed")
    mo.vstack(
        [
            mo.md(r"""
    ## 1. Regions in scope

    | Control | Business meaning |
    |---|---|
    | **Orders a year to count as its own metro** | Metros with fewer orders are pooled into one region, *US: other known metros* |
    | **Regions left out of the test** (below the region list) | Markets whose sales don't reflect ordinary customers, such as staff or one-off bulk buyers |
    | **Random seed** | Technical: fixes the random draws so results repeat |
    """),
            mo.hstack([metro_min, seed], justify="start"),
        ]
    )
    return metro_min, seed


@app.cell
def _(metro_min, np, raw):
    # Map country × metro to test regions; weekly matrices O (orders), R (revenue), B (buyers).
    HIDDEN = {"not available in demo dataset", "(not set)", "", "nan"}
    _d = raw.copy()
    _d["metro"] = _d["metro"].astype(str)
    _us = _d["country"].eq("United States")
    _known = _us & ~_d["metro"].isin(HIDDEN)
    _metro_tot = _d[_known].groupby("metro")["orders"].sum()
    _big = set(_metro_tot[_metro_tot >= metro_min.value].index)

    def _region(row):
        if row.country == "United States":
            if row.metro in HIDDEN:
                return "US: metro unknown"
            return row.metro if row.metro in _big else "US: other known metros"
        if row.country in ("Canada", "Venezuela"):
            return row.country
        return "Other non-US"

    _d["region"] = [_region(r) for r in _d.itertuples()]
    _g = _d.groupby(["region", "wk"])[["orders", "revenue", "buyers"]].sum()
    _weeks = np.arange(52)
    O =_g["orders"].unstack("wk").reindex(columns=_weeks).fillna(0)
    O = O.loc[O.sum(1).sort_values(ascending=False).index]
    R = _g["revenue"].unstack("wk").reindex(index=O.index, columns=_weeks).fillna(0)
    B = _g["buyers"].unstack("wk").reindex(index=O.index, columns=_weeks).fillna(0)
    POOLS = ["US: other known metros", "US: metro unknown"]
    SINGLE = [r for r in O.index if r not in POOLS + ["Canada", "Venezuela", "Other non-US"]]
    REGIONS = list(O.index)
    return B, O, R, REGIONS, SINGLE


@app.cell
def _(REGIONS, mo):
    _default = [r for r in REGIONS if r.startswith("San Francisco") or r == "Venezuela"]
    exclude = mo.ui.multiselect(REGIONS, value=_default, label="Regions left out of the test")
    mo.vstack(
        [
            exclude,
            mo.md(
                "Default: the Bay Area (many buyers are Google staff) and Venezuela (one bulk buyer placed "
                "two thirds of its orders in four weeks). All other regions, in and outside the US, are in."
            ),
        ]
    )
    return (exclude,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. What the data shows
    """)
    return


@app.cell
def _(O, R, REGIONS, exclude, mo, pd):
    UNIVERSE = [r for r in REGIONS if r not in exclude.value]
    orders_wk = O.loc[UNIVERSE].sum().mean()
    sales_yr = R.loc[UNIVERSE].values.sum()
    daily_all = sales_yr / 364
    unknown = O.loc["US: metro unknown"].sum() / O.loc[UNIVERSE].values.sum() if "US: metro unknown" in UNIVERSE else 0.0
    _t = pd.DataFrame(
        {
            "average orders a week": O.loc[UNIVERSE].mean(1).round(1),
            "share of all orders, 52 weeks": (O.loc[UNIVERSE].sum(1) / O.loc[UNIVERSE].values.sum()).map("{:.1%}".format),
            "total sales, 52 weeks ($)": R.loc[UNIVERSE].sum(1).round(0),
        }
    )
    mo.vstack(
        [
            mo.md(
                f"""
    | Number | Value | How it's obtained |
    |---|---|---|
    | Average orders a week, all test regions | **{orders_wk:.1f}** | Total orders over the 52 weeks ÷ 52 (the same as adding up each region's weekly average) |
    | Total sales over the 52 weeks | **\\${sales_yr:,.0f}** | All test regions' revenue, added up over the 52 weeks (364 days) |
    | Average sales a day, all regions | \\${daily_all:,.0f} | Total sales ÷ 364 days |
    | Average sales a day, per group (if split in half) | **\\${daily_all / 2:,.0f}** | Average sales a day ÷ 2; Section 5b's spend cap uses this same half share |
    | Share of all orders with no recorded metro | {unknown:.0%} | US orders whose metro is hidden in the public data ÷ all test-region orders, over the 52 weeks |
    """
            ),
            mo.ui.table(_t, selection=None),
        ]
    )
    return UNIVERSE, daily_all, orders_wk


@app.cell
def _(O, UNIVERSE, alt, mo):
    _w = O.loc[UNIVERSE].T.copy()
    _top = list(O.loc[UNIVERSE].sum(1).sort_values(ascending=False).index[:6])
    _w["Other test regions"] = _w.drop(columns=_top).sum(1)
    _long = _w[_top + ["Other test regions"]].reset_index().melt("wk", var_name="region", value_name="orders")
    _c = (
        alt.Chart(_long)
        .mark_area()
        .encode(x=alt.X("wk:Q", title="Week from 1 Aug 2016"), y=alt.Y("orders:Q", stack=True, title="Orders"),
                color=alt.Color("region:N"), tooltip=["region", "wk", "orders"])
        .properties(height=260, title="Weekly orders by region")
    )
    mo.ui.altair_chart(_c)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Chance and clumping

    **Pure chance.** If many people each have a tiny, independent chance of ordering, weekly orders follow a
    Poisson distribution: variance = average, so the typical variation is √average. Try it:
    """)
    return


@app.cell
def _(mo):
    lam = mo.ui.slider(0.5, 50, step=0.1, value=11.3, label="Average orders a week (λ)", show_value=True)
    lam
    return (lam,)


@app.cell
def _(alt, lam, math, mo, np, pd):
    _x = np.random.default_rng(0).poisson(lam.value, 100_000)
    _h = pd.Series(_x).value_counts().sort_index().reset_index()
    _h.columns = ["orders", "weeks"]
    _c = alt.Chart(_h).mark_bar().encode(x="orders:Q", y="weeks:Q").properties(height=180, width=420)
    mo.hstack(
        [
            _c,
            mo.md(
                f"""
    100,000 simulated weeks:

    - average **{_x.mean():.2f}**
    - variance **{_x.var():.2f}**
    - typical variation √variance = **±{_x.std():.2f}** (√λ = {math.sqrt(lam.value):.2f})
    """
            ),
        ]
    )
    return


@app.cell
def _(O, SINGLE, np):
    def loo_mu(D, u, units, idx=None):
        """Expected orders of region u in week t = u's 52-week average × week-t index of the other regions,
        where index = other regions' total orders in week t ÷ their 52-week average weekly total."""
        other = D.loc[[k for k in units if k != u]].sum().values
        y = D.loc[u].values
        if idx is not None:
            other, y = other[idx], y[idx]
        return y, y.mean() * other / other.mean()

    REF = [r for r in O.index if r != "Venezuela"]  # regions whose weekly totals make the week index (Venezuela: one bulk buyer)
    FIT_UNITS = SINGLE  # single metros (Bay Area included: it is left out of the test, not of the noise fit)
    BIG = [u for u in SINGLE if O.loc[u].mean() >= 2]  # metros used to fit persistence
    _ = np.seterr(all="ignore")  # silence divide/overflow warnings from empty weeks; assigned so it is not displayed
    return BIG, FIT_UNITS, REF, loo_mu


@app.cell
def _(B, FIT_UNITS, O, REF, loo_mu, mo, np, pd, phi, seed):
    def _ratio(y, idx):
        mu = y.mean(axis=-1, keepdims=True) * idx  # expected = own average × week index
        return ((y - mu) ** 2).sum(-1) / np.maximum(mu.sum(-1), 1e-9) * 52 / 51

    _rng = np.random.default_rng(seed.value)
    _rows = []
    _los, _his = [], []
    for _u in FIT_UNITS:
        _y, _mu = loo_mu(O, _u, REF)
        _idx = _mu / _y.mean()
        _obs = float(_ratio(_y, _idx))
        # If purchases were independent: 5,000 years of Poisson orders around the same weekly expected values,
        # each scored exactly like the real data (own average re-estimated each time).
        _sim = _ratio(_rng.poisson(_mu, size=(5000, len(_mu))).astype(float), _idx)
        _lo, _hi = np.percentile(_sim, [2.5, 97.5])
        _los.append(_lo)
        _his.append(_hi)
        _rows.append(
            dict(metro=_u, orders_a_week=round(_y.mean(), 1), variance_over_average=round(_obs, 2),
                 independent_95pct_range=f"{_lo:.2f} – {_hi:.2f}",
                 verdict="above" if _obs > _hi else ("below" if _obs < _lo else "within"),
                 orders_per_buyer=round(O.loc[_u].sum() / max(B.loc[_u].sum(), 1), 2))
        )
    ratios = pd.DataFrame(_rows)
    _rlo, _rhi = min(_los), max(_his)
    _show = ratios.rename(columns={"orders_a_week": "average orders a week", "variance_over_average": "variance ÷ average",
                                   "independent_95pct_range": "95% range if purchases independent",
                                   "orders_per_buyer": "orders per buyer"})
    mo.vstack(
        [
            mo.md(
                rf"""
    **Clumping in the real data.** For each single metro and each week, all from the real orders:

    1. **Week index** = total orders that week in all *other* regions (Venezuela left out) ÷ their average weekly
       total over the 52 weeks. 1.2 means the rest of the store was 20% busier than usual that week.
    2. **Expected orders** = the metro's average weekly orders over the 52 weeks × the week index.
    3. **Variance ÷ average** = Σ (actual − expected)² ÷ Σ expected, over the 52 weeks, × 52/51.
       The expected values add up to the actual total, so the denominator is also the metro's actual average × 52.

    Pure chance gives about 1. Orders per buyer (total orders ÷ total weekly buyers) above 1 shows why it is higher:
    one buyer often places several orders.

    **Clumping, in business terms.** Pure chance assumes every order is an independent purchase: a separate customer
    deciding on their own. In practice one decision often produces several orders: a customer splits a purchase,
    comes back for a second item, or buys for a team or event. Those orders arrive together, so weekly counts jump
    in bunches instead of one at a time, and vary more than independent purchases would.

    The clumping number (about {phi:.1f}) is **not** any one metro's ratio below, nor their average. Each metro's ratio
    mixes clumping, which is the same everywhere, with the metro's own swing, which grows with its size. Section 4
    separates them: clumping is the ratio a metro would have if it were too small for its swing to matter, and it
    means weekly variance is about {phi:.1f} times what independent purchases would give.

    **Reading the ratio.** Even if purchases were independent, a metro's ratio would not be exactly 1 in a single
    year. The column *95% range if purchases independent* shows where it would fall 95% of the time: 5,000 simulated years of
    independent (Poisson) orders around the metro's own weekly expected values, scored the same way. It comes out
    at about {_rlo:.2f} to {_rhi:.2f} for every metro: with 52 weeks, a ratio's chance spread barely depends on size. With {len(ratios)}
    metros, about one in 20 would fall outside it by chance alone, so a value just past the edge is weak evidence.

    | Verdict | What it indicates |
    |---|---|
    | **within** | The metro's weekly ups and downs are no larger than independent purchases would give: each order looks like a separate customer's decision, and the metro has no clear busy or quiet spells of its own |
    | **above** | More variation than independent purchases: orders arrive in bunches (one buyer placing several; see orders per buyer), the metro has busy and quiet spells of its own, or both. Section 4 separates the two. These metros add the most noise to the test |
    | **below** | Less variation than independent purchases: orders more regular than chance, as with subscriptions, scheduled reorders or capped stock. Poisson would not describe the metro, and the noise model would overstate its noise |
    """
            ),
            mo.ui.table(_show, selection=None),
        ]
    )
    return (ratios,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Regional swing

    Under the noise model, **variance ÷ average = clumping + swing² × average**: clumping lifts every metro's
    ratio by the same amount; a region's own swing lifts it more the bigger the metro. Fitting this line
    (weighted, so metros with more data count more) gives both numbers.

    **Persistence** is fitted separately, on the metros with at least 2 orders a week: multiply each week's leftover
    (actual − expected orders) by the next week's, add up, divide by the matching sum of expected orders (this week
    × next week), then by swing². Chance and clumping don't carry from week to week, so this picks up only the swing.

    Ranges come from rebuilding the year from random 4-week blocks (to keep
    runs of busy or quiet weeks together), refitting each time, and taking the middle share of the results:
    for a 95% range, the 2.5th to 97.5th percentiles.
    """)
    return


@app.cell
def _(mo):
    n_boot = mo.ui.slider(100, 3000, step=100, value=1000, label="Rebuilt years for the ranges", show_value=True)
    ci_level = mo.ui.dropdown({"95%": 0.95, "90%": 0.90, "80%": 0.80}, value="95%", label="Range: confidence level")
    mo.hstack([n_boot, ci_level], justify="start")
    return ci_level, n_boot


@app.cell
def _(BIG, FIT_UNITS, O, REF, loo_mu, math, nnls, np):
    def fit_noise(D, idx=None, iters=8):
        """phi (clumping), s2 (swing²) from a weighted moment fit of (y - mu)² ≈ phi·mu + s2·mu²."""
        pairs = [loo_mu(D, u, REF, idx) for u in FIT_UNITS]
        n = len(pairs[0][0])
        phi, s2 = 1.0, 0.05
        for _ in range(iters):
            X, Y = [], []
            for y, mu in pairs:
                r = ((y - mu) ** 2).sum() * n / (n - 1)
                V = phi * mu + s2 * mu ** 2
                w = 1 / math.sqrt(2 * (V ** 2).sum())
                X.append([mu.sum() * w, (mu ** 2).sum() * w])
                Y.append(r * w)
            (phi, s2), _ = nnls(np.array(X), np.array(Y))
        return float(phi), float(s2)

    def lag1(D, idx=None):
        num = den = 0.0
        for u in BIG:
            y, mu = loo_mu(D, u, REF, idx)
            e = y - mu
            num += (e[:-1] * e[1:]).sum()
            den += (mu[:-1] * mu[1:]).sum()
        return num / den

    phi, s2 = fit_noise(O)
    sigma = math.sqrt(s2)
    rho = float(np.clip(lag1(O) / s2, 0, 0.95)) if s2 > 0 else 0.0
    return fit_noise, lag1, phi, rho, s2, sigma


@app.cell
def _(O, ci_level, fit_noise, lag1, n_boot, np, seed):
    _rng = np.random.default_rng(seed.value)
    _res = []
    for _ in range(n_boot.value):
        _st = _rng.integers(0, 52 - 4 + 1, 13)
        _idx = np.concatenate([np.arange(s, s + 4) for s in _st])[:52]
        _p, _s = fit_noise(O, _idx)
        _r = np.clip(lag1(O, _idx) / _s, 0, 0.95) if _s > 1e-9 else np.nan
        _res.append((_p, np.sqrt(_s), _r))
    boot = np.array(_res)
    _tail = (1 - ci_level.value) / 2 * 100  # e.g. 95% -> 2.5th and 97.5th percentiles
    ranges = {k: np.nanpercentile(boot[:, i], [_tail, 100 - _tail]) for i, k in enumerate(["phi", "sigma", "rho"])}
    return (ranges,)


@app.cell
def _(alt, ci_level, mo, np, pd, phi, ranges, ratios, rho, s2, sigma):
    _line = pd.DataFrame({"orders_a_week": np.linspace(0, ratios.orders_a_week.max() * 1.05, 50)})
    _line["fit"] = phi + s2 * _line.orders_a_week
    _pts = alt.Chart(ratios).mark_circle(size=70).encode(
        x=alt.X("orders_a_week:Q", title="Orders a week"),
        y=alt.Y("variance_over_average:Q", title="Variance ÷ average"),
        tooltip=["metro", "orders_a_week", "variance_over_average"])
    _fit = alt.Chart(_line).mark_line(strokeDash=[4, 3]).encode(x="orders_a_week:Q", y="fit:Q")
    _one = alt.Chart(pd.DataFrame({"y": [1]})).mark_rule(opacity=0.4).encode(y="y:Q")
    _cmp = ratios[["metro", "orders_a_week", "variance_over_average"]].rename(
        columns={"variance_over_average": "observed ratio"})
    _cmp["clumping part"] = round(phi, 2)
    _cmp["swing part"] = (s2 * _cmp.orders_a_week).round(2)
    _cmp["fitted ratio"] = (phi + s2 * _cmp.orders_a_week).round(2)
    mo.vstack(
        [
            mo.hstack(
                [
                    mo.ui.altair_chart((_pts + _fit + _one).properties(height=260, width=420)),
                    mo.md(
                        f"""
    | Term | Value | Unit | {ci_level.value:.0%} range |
    |---|---|---|---|
    | Clumping (line at size 0) | **{phi:.2f}** | × the weekly variance independent purchases would give | {ranges['phi'][0]:.2f} – {ranges['phi'][1]:.2f} |
    | Swing (√ slope) | **{sigma:.0%}** | % of the region's normal weekly level (typical size of a week's swing) | {ranges['sigma'][0]:.0%} – {ranges['sigma'][1]:.0%} |
    | Persistence (how long a swing lasts) | **{rho:.2f}** | share of one week's swing still there the next week (0 = gone, 1 = all of it); no time unit | {ranges['rho'][0]:.2f} – {ranges['rho'][1]:.2f} |

    Persistence {rho:.2f} means about {rho:.0%} of a busy week's extra carries into the next week and {rho ** 2:.0%}
    into the week after.

    Dashed: fitted line, ratio = {phi:.2f} + {s2:.3f} × orders a week. Grey: pure chance (1).
    """
                    ),
                ]
            ),
            mo.md(
                "**Each metro's ratio, split into its two parts.** The clumping part is the same for every metro; "
                "the swing part grows with size. Observed ratios scatter around the fitted ones because 52 weeks of "
                "a few orders is a small sample."
            ),
            mo.ui.table(_cmp, selection=None),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### The noise model and its basis

    For region $r$ in week $t$, with expected orders $\mu_{rt}$ = the region's average × the week index:

    $$\text{orders}_{rt} \sim \text{clumped Poisson}\big(\mu_{rt}\, g_{rt}\big), \qquad
    g_{rt} = e^{\sigma z_{rt} - \sigma^2/2}, \qquad z_{rt} = \rho\, z_{r,t-1} + \sqrt{1-\rho^2}\,\varepsilon_{rt}$$

    This gives two moment equations, which are what Sections 3 and 4 fit:

    | Equation | Fits | Meaning |
    |---|---|---|
    | $\text{Var}(\text{orders}_{rt}) = \varphi\,\mu_{rt} + \sigma^2 \mu_{rt}^2$ | Clumping $\varphi$, swing $\sigma$ | One week's spread: chance with clumping, plus the region's own swing |
    | $\text{Cov}(\text{orders}_{rt}, \text{orders}_{r,t+k}) = \rho^k \sigma^2 \mu_{rt}\, \mu_{r,t+k}$ | Persistence $\rho$ ($k = 1$) | Only the swing carries between weeks, fading by $\rho$ each week |

    | Piece | Basis |
    |---|---|
    | Counts around a hidden level that carries week to week, fitted from the leftovers' squares and products | Zeger (1988), *A regression model for time series of counts*, Biometrika 75(4): the same two equations and moment estimates (with $\varphi = 1$) |
    | Variance above Poisson ($\varphi\mu$ and $\sigma^2\mu^2$ terms) | Overdispersed count models: quasi-Poisson and negative binomial (McCullagh & Nelder, *Generalized Linear Models*, 1989) |
    | Clumping: one decision, several orders | Compound Poisson process |
    | Expected = region average × week index | Multiplicative region × week model, leaving each region out of its own index |
    | Ranges from rebuilding the year in 4-week blocks | Moving block bootstrap: Künsch (1989), *Annals of Statistics* 17(3) |
    | Detectable lift from fake tests | Power analysis by simulation |

    Published geo-test tools (GeoLift, matched_markets, trimmed_match) size tests by replaying the real regions'
    history instead of fitting a noise model. Here that replay is the "Scaled by real data" check in Section 5b, because the public data
    has one year and hides the metro for most orders.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Regions and split: the fake regions

    Fake regions are made-up regions with no names, only sizes, whose weekly orders vary like the real
    data (clumping, swing, persistence). Sizes fall off from large to small the way the real metros'
    do (a power law fitted to the single US metros in the test) and add up to the real total. Any region over
    the cap is split, as a large metro would be split into postal-code areas. Regions are paired by size and a
    coin flip in each pair picks the campaign region.
    """)
    return


@app.cell
def _(mo):
    cap = mo.ui.slider(0.05, 0.5, step=0.01, value=0.10, label="Largest region, share of orders", show_value=True)
    n_regions = mo.ui.slider(8, 60, step=1, value=24, label="Fake regions before splitting", show_value=True)
    mo.vstack(
        [
            mo.md(r"""
    | Control | Business meaning |
    |---|---|
    | **Largest region, share of orders** | Keeps any single market from deciding the result. Lower means splitting more big metros into postal-code areas |
    | **Fake regions before splitting** | How many markets the store can run the test in. More markets give a more precise test |
    """),
            mo.hstack([cap, n_regions], justify="start"),
        ]
    )
    return cap, n_regions


@app.cell
def _(O, SINGLE, UNIVERSE, cap, math, n_regions, np, orders_wk):
    def zipf_sizes(K, M, s):
        w = 1 / np.arange(1, K + 1) ** s
        return M * w / w.sum()

    def split_cap(mu, c):
        out, tot = [], mu.sum()
        for m in mu:
            k = max(1, math.ceil(m / (c * tot)))
            out += [m / k] * k
        return np.sort(np.array(out))[::-1]

    _v = np.sort(O.loc[[u for u in SINGLE if u in UNIVERSE]].mean(1).values)[::-1]
    zipf_s = float(-np.polyfit(np.log(np.arange(1, len(_v) + 1)), np.log(_v), 1)[0])
    mu_plan = split_cap(zipf_sizes(n_regions.value, orders_wk, zipf_s), cap.value)
    return mu_plan, zipf_s


@app.cell
def _(alt, cap, mo, mu_plan, n_regions, np, pd, seed, zipf_s):
    _rng = np.random.default_rng(seed.value)
    _order = np.argsort(-mu_plan)
    _grp = np.empty(len(mu_plan), dtype=object)
    for _a in range(0, len(_order) - 1, 2):
        _i, _j = _order[_a], _order[_a + 1]
        if _rng.random() < 0.5:
            _i, _j = _j, _i
        _grp[_i], _grp[_j] = "campaign", "comparison"
    if len(_order) % 2:
        _grp[_order[-1]] = "campaign" if _rng.random() < 0.5 else "comparison"
    _df = pd.DataFrame({"region": np.arange(1, len(mu_plan) + 1), "orders_a_week": mu_plan.round(2), "group": _grp})
    _c = alt.Chart(_df).mark_bar().encode(x="region:O", y="orders_a_week:Q", color="group:N",
                                          tooltip=["region", "orders_a_week", "group"]).properties(height=220)
    _tot = _df.groupby("group").orders_a_week.sum()
    mo.vstack(
        [
            mo.md(
                f"**{len(mu_plan)} fake regions** (size slope {zipf_s:.2f}); the largest holds "
                f"{mu_plan.max() / mu_plan.sum():.0%} of orders. One example split: campaign "
                f"{_tot.get('campaign', 0):.1f} vs comparison {_tot.get('comparison', 0):.1f} orders a week."
            ),
            mo.ui.altair_chart(_c),
            mo.md(
                f"""
    **Why {len(mu_plan)} regions.** The starting count ({n_regions.value}, set by the *fake regions before splitting*
    control) is a working assumption, not taken from the data: the public data names only a few single metros and
    hides the metro for most orders, so it can't say how many markets the store has. The default follows the plan's
    working figure of about 20 metros plus a few outside the US. Splitting every region over the
    {cap.value:.0%} cap then gives {len(mu_plan)}. The count matters: each region's swing averages out only across
    regions, so fewer regions mean a larger detectable lift. Replace it with the store's own count of targetable
    markets once orders can be located by shipping address.
    """
            ),
        ]
    )
    return


@app.cell
def _(math, np):
    LIFTS = np.round(np.arange(0.0, 0.81, 0.05), 2)

    def simulate(mu, A, F, phi, sigma, rho, reps, rng, lifts=LIFTS, H=52):
        """Fake tests. Returns (estimates per lift: reps array, mean campaign share of orders)."""
        K, n = len(mu), H + A + F
        z = np.empty((reps, K, n))
        z[..., 0] = rng.standard_normal((reps, K))
        c = math.sqrt(1 - rho ** 2)
        for t in range(1, n):
            z[..., t] = rho * z[..., t - 1] + c * rng.standard_normal((reps, K))
        lam = mu[None, :, None] * np.exp(sigma * z - sigma ** 2 / 2)
        order = np.argsort(-mu)
        npair = K // 2
        a, b = order[0:2 * npair:2], order[1:2 * npair:2]
        flip = rng.random((reps, npair)) < 0.5
        camp = np.zeros((reps, K), bool)
        np.put_along_axis(camp, np.where(flip, b, a), True, axis=1)
        if K % 2:
            camp[:, order[-1]] = rng.random(reps) < 0.5
        share = float(((mu[None, :] * camp).sum(1) / mu.sum()).mean())
        k = 1 / (phi - 1) if phi > 1.0001 else None
        out = {}
        for lift in lifts:
            ll = lam.copy()
            ll[:, :, H:] *= np.where(camp, 1 + lift, 1.0)[..., None]
            y = rng.poisson(rng.gamma(ll * k, 1 / k)) if k else rng.poisson(ll)
            pre, post = y[..., :H].sum(-1), y[..., H:].sum(-1)
            tp, tq = np.maximum((pre * camp).sum(1), 0.5), np.maximum((post * camp).sum(1), 0.5)
            cp, cq = np.maximum((pre * ~camp).sum(1), 0.5), np.maximum((post * ~camp).sum(1), 0.5)
            out[float(lift)] = np.log(tq / cq) - np.log(tp / cp)
        return out, share

    def read_power(est, z_a, target):
        """Noise, bar, power per lift and the smallest lift detected `target` of the time."""
        se = float(est[0.0].std())
        bar = z_a * se
        pw = {l: float((v > bar).mean()) for l, v in est.items() if l > 0}
        ls = sorted(pw)
        mde = None
        if pw[ls[0]] >= target:
            mde = ls[0]
        for lo, hi in zip(ls, ls[1:]):
            if mde is None and pw[lo] < target <= pw[hi]:
                mde = lo + (hi - lo) * (target - pw[lo]) / (pw[hi] - pw[lo])
        fa = float((est[0.0] > bar).mean())
        return dict(se=se, bar=bar, power=pw, mde=mde, false_alarm=fa)
    return (simulate,)


@app.cell
def _(mo):
    margin = mo.ui.slider(0.2, 0.8, step=0.05, value=0.5, label="Gross margin", show_value=True)
    power = mo.ui.slider(0.5, 0.95, step=0.05, value=0.8, label="Power", show_value=True)
    alpha = mo.ui.dropdown({"5%": 0.05, "10%": 0.10, "1%": 0.01}, value="5%", label="False-alarm rate")
    sided = mo.ui.radio(["two-sided", "one-sided"], value="two-sided", label="Test")
    follow = mo.ui.slider(0, 8, step=1, value=4, label="Weeks of follow-up", show_value=True)
    reps = mo.ui.slider(200, 3000, step=100, value=1500, label="Fake tests per setting", show_value=True)
    mo.vstack(
        [
            mo.md(r"""
    ## 5b. Detectable lift and spend cap

    | Control | Business meaning |
    |---|---|
    | **Gross margin** | Share of each sales dollar kept as profit. Sets break-even: each ad dollar must bring 1 ÷ margin of extra sales (\$2 at 50%) |
    | **Power** | Chance the test catches a lift of the stated size. 80% means it misses 1 in 5 |
    | **False-alarm rate** | Chance of seeing a "lift" when the ads did nothing, and so scaling a campaign that doesn't work |
    | **Test: two-sided / one-sided** | Two-sided also guards against misreading a harmful campaign; one-sided only asks "is it worth scaling?" and needs a smaller test |
    | **Weeks of follow-up** | How long to keep counting after the ads stop, to catch later purchases. Delays the answer; costs no ad spend |
    | **Fake tests per setting** | Technical: how precisely the notebook estimates |
    """),
            mo.hstack([margin, power], justify="start"),
            mo.hstack([alpha, sided, follow], justify="start"),
            reps,
        ]
    )
    return alpha, follow, margin, power, reps, sided


@app.cell
def _(margin):
    breakeven = 1 / margin.value
    r_star = breakeven  # the test is sized for a campaign that exactly breaks even
    return


@app.cell
def _(alpha, norm, power, sided):
    z_a = float(norm.ppf(1 - alpha.value / 2) if sided.value == "two-sided" else norm.ppf(1 - alpha.value))
    z_b = float(norm.ppf(power.value))
    return z_a, z_b


@app.cell
def _(mo):
    mo.md(r"""
    ### Smallest detectable lift by length

    For each length of ads (plus the follow-up weeks), two estimates of the smallest lift detected with the chosen
    power:

    - **Model only:** fake tests on the planned regions (Section 5) with the fitted clumping, swing and persistence.
    - **Scaled by real data:** the same, with the noise multiplied by (real ÷ model noise) measured on the real regions
      at the same length. *Real noise:* fake tests replayed on the real regions' own weeks: random pairings, every window
      in the year with at least 13 weeks of history before it, no change made. *Model noise:* the model on regions of
      exactly those sizes. Only lengths that fit in one year can be checked.

    Smallest detectable lift = e^((critical z + power z) × noise) − 1. **95% ranges:** the year is rebuilt from random
    4-week blocks many times; each time the three numbers are refitted, the model re-simulated and the real data
    replayed, and the middle 95% of the results is kept.
    """)
    return


@app.cell
def _(mo):
    curve_boot = mo.ui.slider(20, 300, step=20, value=20, label="Rebuilt years for the 95% ranges", show_value=True)
    curve_run = mo.ui.run_button(label="Compute detectable lift by length (about a minute)")
    mo.hstack([curve_boot, curve_run], justify="start")
    return curve_boot, curve_run


@app.cell
def _(
    AUTORUN,
    O,
    REF,
    UNIVERSE,
    curve_boot,
    curve_run,
    fit_noise,
    follow,
    lag1,
    math,
    mo,
    mu_plan,
    np,
    pd,
    phi,
    reps,
    rho,
    seed,
    sigma,
    simulate,
    z_a,
    z_b,
):
    mo.stop(not (curve_run.value or AUTORUN), mo.md("*Press the button to compute the curve.*"))
    _F = follow.value
    _Z = z_a + z_b
    _rng = np.random.default_rng(seed.value + 7)
    _real_units = [u for u in UNIVERSE if u in REF and u != "US: metro unknown"]
    _Y = O.loc[_real_units].values
    _MODEL_ONLY = [2, 4, 8, 13, 16, 20, 26, 39, 52]
    _CHECKED = [A for A in _MODEL_ONLY if 13 + A + _F <= 52 and A <= 26]

    def _mde(se):
        return math.exp(_Z * se) - 1

    def _model_se(mu, A, p, s, r, n, H):
        return float(simulate(mu, A, _F, p, s, r, n, _rng, lifts=[0.0], H=H)[0][0.0].std())

    def _replay_se(Y, A, P):
        """Real noise: random pairings over every window with >= 13 weeks of history."""
        _W = A + _F
        _sizes = Y.mean(1)
        _order = np.argsort(-_sizes)
        _K = len(_sizes)
        _cm = np.zeros((P, _K), bool)
        for _a in range(0, _K - 1, 2):
            _pick = _rng.random(P) < 0.5
            _cm[np.arange(P), np.where(_pick, _order[_a + 1], _order[_a])] = True
        if _K % 2:
            _cm[:, _order[-1]] = _rng.random(P) < 0.5
        _est = []
        for _s in range(13, 52 - _W + 1):
            _pre, _post = Y[:, :_s].sum(1), Y[:, _s:_s + _W].sum(1)
            _est.append(np.log(np.maximum(_cm @ _post, .5) / np.maximum((~_cm) @ _post, .5))
                        - np.log(np.maximum(_cm @ _pre, .5) / np.maximum((~_cm) @ _pre, .5)))
        return float(np.concatenate(_est).std())

    # parameter draws from rebuilt years (same method as Section 4's ranges)
    _idxs, _draws = [], []
    for _ in range(curve_boot.value):
        _st = _rng.integers(0, 52 - 4 + 1, 13)
        _idx = np.concatenate([np.arange(_s, _s + 4) for _s in _st])[:52]
        _p, _s2 = fit_noise(O, _idx)
        _r = float(np.clip(lag1(O, _idx) / _s2, 0, 0.95)) if _s2 > 1e-9 else 0.0
        _idxs.append(_idx)
        _draws.append((_p, math.sqrt(_s2), _r))

    _rows = []
    for _A in _MODEL_ONLY:
        _se_plan = _model_se(mu_plan, _A, phi, sigma, rho, reps.value, 52)
        _row = dict(weeks=_A, model=_mde(_se_plan))
        _bm, _bs = [], []
        for _idx, (_p, _s, _r) in zip(_idxs, _draws):
            _se_b = _model_se(mu_plan, _A, _p, _s, _r, 250, 52)
            _bm.append(_mde(_se_b))
            if _A in _CHECKED:
                _Yb = _Y[:, _idx]
                _H = (13 + 52 - _A - _F) // 2
                _ratio_b = _replay_se(_Yb, _A, 40) / _model_se(_Yb.mean(1), _A, _p, _s, _r, 250, _H)
                _bs.append(_mde(_se_b * _ratio_b))
        _row["model_lo"], _row["model_hi"] = np.percentile(_bm, [2.5, 97.5])
        if _A in _CHECKED:
            _H = (13 + 52 - _A - _F) // 2
            _ratio = _replay_se(_Y, _A, 200) / _model_se(_Y.mean(1), _A, phi, sigma, rho, reps.value, _H)
            _row.update(ratio=_ratio, scaled=_mde(_se_plan * _ratio))
            _row["scaled_lo"], _row["scaled_hi"] = np.percentile(_bs, [2.5, 97.5])
        _rows.append(_row)
    lift_curve = pd.DataFrame(_rows)
    return (lift_curve,)


@app.cell
def _(alt, curve_boot, lift_curve, mo, pd, power):
    _m = lift_curve.assign(basis="Model only")[["weeks", "basis", "model", "model_lo", "model_hi"]]
    _m.columns = ["weeks", "basis", "lift", "lo", "hi"]
    _s = lift_curve.dropna(subset=["scaled"]).assign(basis="Scaled by real data")[["weeks", "basis", "scaled", "scaled_lo", "scaled_hi"]]
    _s.columns = ["weeks", "basis", "lift", "lo", "hi"]
    _d = pd.concat([_m, _s])
    _color = alt.Color("basis:N", scale=alt.Scale(domain=["Model only", "Scaled by real data"], range=["#2a78d6", "#d9822b"]),
                       title=None)
    _x = alt.X("weeks:Q", title="Weeks of ads (plus follow-up)")
    _band = alt.Chart(_d).mark_area(opacity=0.15).encode(x=_x, y=alt.Y("lo:Q", axis=alt.Axis(format="%")), y2="hi:Q", color=_color)
    _line = alt.Chart(_d).mark_line(point=True).encode(
        x=_x, y=alt.Y("lift:Q", axis=alt.Axis(format="%"), title=f"Smallest lift detected {power.value:.0%} of the time"),
        color=_color, tooltip=["basis", "weeks", alt.Tooltip("lift:Q", format=".1%"), alt.Tooltip("lo:Q", format=".1%"),
                               alt.Tooltip("hi:Q", format=".1%")])
    mo.vstack([
        mo.ui.altair_chart((_band + _line).properties(height=300, width=640)),
        mo.md(rf"""
    **How sure are these numbers?** Lines are the best estimates; shaded bands show how much they could move.
    We have only one year of sales, so to see how different another year might look, we build {curve_boot.value} "rebuilt years"
    by re-picking the real year's sales a month (4 weeks) at a time: some months get picked twice, others not at all.
    The calculation is redone for each alternative year, and the band covers the middle 95% of the answers.

    - **Blue, model only:** how much the estimate moves when the sales noise is re-measured in each alternative year.
      It doesn't cover the model itself being off (Section 4).
    - **Orange, scaled by real data:** a rough guide only. Re-picking months scrambles the order of the year, which this
      line depends on, so its band is probably wider than the real uncertainty. It stops at the longest test that,
      with enough weeks before it to compare against, still fits inside one year of data.
    """),
    ])
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Why the two lines differ, and which to trust**

    Week by week, the real data is about as noisy as the model. But the test compares totals over the whole window, and
    there the real regions are steadier: a busy week tends to be followed by quieter ones, while the model lets busy
    spells add up, and gives every region New York's large swings.

    **The orange line may be too optimistic:**

    - **One year.** The rebuilt years only re-pick months from the same 52 real weeks. They show how much the result
      moves within this year, not how a different year with its own events (a worse holiday season, a long regional
      slump) would behave; such a year could be noisier.
    - **Overlapping replays.** They share most of their weeks, so they understate how much results could vary.
    - **Shorter comparison periods.** Inside one year, each replay can compare against only 13 to 38 weeks before the
      test, not the full year the real test would have.
    - **A possible artefact.** Expected orders come from the other regions' totals; in a small store a region's busy week
      also nudges that total, which can make its ups and downs look like they cancel.
    - **Few regions.** Only the 13 regions with a known location can be replayed, without most of the orders.

    **Is the blue line an upper limit?** Probably on the high side, but not guaranteed. It was built to be cautious
    (one large swing for every region, plus carry-over), yet it can only reflect what one year shows: a worse year,
    month-long regional shocks or a different holiday season could make the real test noisier still.

    **Rule of thumb for more data.** This study rests on 52 weeks. To replay a test properly you need a full year to
    compare against plus the test window itself, repeated several times:
    *weeks of history needed ≈ 52 + (number of independent replays × test window)*. For a 13-week test (17-week
    window) and about 6 independent replays: 52 + 6 × 17 ≈ 154 weeks, **about 3 years**. Two years is the minimum
    to replay even one full-length test against a full year. The uncertainty in the fitted swing shrinks roughly with
    the square root of the years of data, so 4 years would about halve today's range.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Most ad spend that breaks even, by length

    If the ads lift the campaign group's sales by exactly the smallest detectable lift, the extra sales over the window
    are lift × the group's normal sales. At the gross margin, those extra sales bring
    **gross profit = margin × lift × normal sales**. That is the most the ads can cost and still break even, the
    **spend cap**. Spend below it and a campaign at that lift makes money; above it, it loses money.
    """)
    return


@app.cell
def _(daily_all, follow, lift_curve, margin, mo, pd):
    S0 = daily_all * 0.5  # campaign group's sales a day: expected share under coin flips in pairs
    _F = follow.value
    _rows = []
    for _, _r in lift_curve.iterrows():
        _A = int(_r.weeks)
        _base = S0 * 7 * (_A + _F)
        _cap = lambda L: margin.value * L * _base
        _row = {"weeks of ads": _A, "normal sales over the window": f"${_base:,.0f}",
                "lift, model only": f"{_r.model:.0%} ({_r.model_lo:.0%}–{_r.model_hi:.0%})",
                "spend cap, model only": f"${_cap(_r.model):,.0f} (${_cap(_r.model) / (7 * _A):,.0f}/day)"}
        if pd.notna(_r.get("scaled")):
            _row["lift, scaled"] = f"{_r.scaled:.0%} ({_r.scaled_lo:.0%}–{_r.scaled_hi:.0%})"
            _row["spend cap, scaled"] = (f"${_cap(_r.scaled):,.0f} (${_cap(_r.scaled) / (7 * _A):,.0f}/day; "
                                         f"range ${_cap(_r.scaled_lo):,.0f}–${_cap(_r.scaled_hi):,.0f})")
        else:
            _row["lift, scaled"] = _row["spend cap, scaled"] = "—"
        _rows.append(_row)
    mo.vstack([
        mo.ui.table(pd.DataFrame(_rows), selection=None),
        mo.md(f"Normal sales over the window = campaign group's average sales a day (\\${S0:,.0f}: all test regions' "
              f"\\${daily_all:,.0f} × 50%) × 7 × (ads weeks + {_F} follow-up weeks). "
              f"Spend cap = {margin.value:.0%} × lift × normal sales; per day = cap ÷ (7 × ads weeks)."),
    ])
    return (S0,)


@app.cell
def _(lift_curve, mo):
    pick_weeks = mo.ui.dropdown([str(int(w)) for w in lift_curve.weeks], value="13", label="Weeks of ads to examine below")
    pick_basis = mo.ui.radio(["Model only", "Scaled by real data"], value="Model only", label="Noise basis")
    mo.vstack([
        mo.md("**Carry one length into Section 6,** which shows the bar for a real lift and the outcomes by true lift."),
        mo.hstack([pick_weeks, pick_basis], justify="start"),
    ])
    return pick_basis, pick_weeks


@app.cell
def _(S0, follow, lift_curve, margin, mo, pd, pick_basis, pick_weeks):
    A_used = int(pick_weeks.value)
    _r = lift_curve[lift_curve.weeks == A_used].iloc[0]
    _scaled = pick_basis.value == "Scaled by real data" and pd.notna(_r.get("scaled"))
    lift_used = float(_r.scaled if _scaled else _r.model)
    total_used = margin.value * lift_used * S0 * 7 * (A_used + follow.value)
    daily_used = total_used / (7 * A_used)
    mo.callout(mo.md(f"### {A_used} weeks of ads + {follow.value} of follow-up · smallest detectable lift "
                     f"{lift_used:.0%} ({'scaled by real data' if _scaled else 'model only'}) · spend cap "
                     f"\\${daily_used:,.0f} a day, \\${total_used:,.0f} in total"), kind="success")
    return A_used, lift_used, total_used


@app.cell
def _(
    A_used,
    S0,
    alpha,
    follow,
    lift_used,
    margin,
    math,
    mo,
    norm,
    sided,
    total_used,
    z_a,
    z_b,
):
    _se = math.log(1 + lift_used) / (z_a + z_b)  # noise implied by Section 5b
    _bar = math.exp(z_a * _se) - 1
    _detect = lambda L: 1 - norm.cdf(z_a - math.log(1 + L) / _se)
    _base = S0 * 7 * (A_used + follow.value)
    _fa = alpha.value / 2 if sided.value == "two-sided" else alpha.value
    _side = ", upper side only" if sided.value == "two-sided" else ""
    _money = lambda x: f"{'−' if x < -0.5 else ('+' if x > 0.5 else '')}\\${abs(x):,.0f}"
    _rows = []
    for _k, _label in ((0.0, "no effect"), (0.5, "half"), (1.0, "smallest detectable"), (1.5, "1.5 ×"), (2.0, "double")):
        _L = lift_used * _k
        _rows.append(f"| {_L:.0%} ({_label}) | {_detect(_L):.0%} | {_money(margin.value * _L * _base - total_used)} |")
    _outcomes = "\n    ".join(_rows)  # keep the table's indentation
    mo.md(
        f"""
    ## 6. Reading the chosen test

    **Question: did the ads do anything?** Null hypothesis: lift = 0. Test: {A_used} weeks of ads + {follow.value} of
    follow-up, spend cap \\${total_used:,.0f}; noise = ln(1 + {lift_used:.1%}) ÷ ({z_a:.2f} + {z_b:.2f}) = {_se:.1%}.

    | Observed lift | Reading |
    |---|---|
    | Below **{_bar:.0%}** (the bar = {z_a:.2f} × noise) | No evidence the ads did anything. With no real effect, a lift above the bar happens {_fa:.1%} of the time (the {alpha.value:.0%} false-alarm rate{_side}) |
    | **{_bar:.0%}** or more | The ads did something. The observed lift is the best estimate of the true lift: at the spend cap, {lift_used:.0%} or more pays back |

    | True lift | If the true lift is this, chance the test detects it | Profit at the spend cap |
    |---|---|---|
    {_outcomes}

    **Reading the chance.** Suppose the ads truly raise sales by the lift in the first column. Weekly sales bounce
    around, so the lift the test measures comes out somewhat higher or lower than the truth. The chance is how often it
    comes out at or above the bar ({_bar:.0%}), so the test reports that the ads worked. Bigger true lifts are caught
    more often; the smallest detectable lift ({lift_used:.0%}) is where the chance reaches {_detect(lift_used):.0%}. It is *not*
    the chance that a reported lift is real: that also depends on how likely the ads were to work in the first place.

    Profit = {margin.value:.0%} margin × true lift × normal sales over the window (\\${_base:,.0f}) − spend cap, before
    content costs. Confirming payback, rather than any lift, would need a stricter test against lift = {lift_used:.0%}.
    """
    )
    return


if __name__ == "__main__":
    app.run()
