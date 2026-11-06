# Proposed fixture: pending owner review
"""Constructed stand-ins for recorded programs. None of them is an external agent's output.

CORRECT: one plausible program per task, written by Claude in the style of a code-writing agent
(read the file, compute, print ``@name[value]``). Each must match the gold on the original data;
``write_programs.py`` checks that before the audit uses it.

MISTAKES: programs with one typical mistake, made from a CORRECT program by a text replacement.
The list of mistake kinds and the rule for applying them were written before any audit ran:

  M1 dropna_forgotten    a program that drops missing values loses that step
  M2 truncated           a mean or a standard deviation goes through int()
  M3 median_for_mean     a mean is replaced by a median (or the reverse)
  M4 unstable_head       "the first of the highest" is taken with sort_values(...).head(1) on a
                         key that can tie, instead of idxmax / a tie rule
  M5 case_sensitive      an exact text comparison where the correct program normalizes case (one task)
  M6 join_fan_out        not applicable: every selected task reads one file

Rule: every CORRECT program gets each of M1 to M5 for which its text contains the pattern the
mistake replaces, in the order listed. No mistake was chosen by what an audit finds.
"""

from __future__ import annotations

CORRECT: dict[int, str] = {}


def correct(question: int, code: str) -> None:
    CORRECT[question] = code.strip() + "\n"


correct(
    19,
    """
import pandas as pd
from scipy.stats import skew
x = pd.read_csv("unemployement_industry.csv")["Mar.2020"].dropna()
s = round(skew(x), 2)
print(f"@is_normal[{'Yes' if -0.5 <= s <= 0.5 else 'No'}]")
""",
)
correct(
    25,
    """
import pandas as pd
x = pd.read_csv("insurance.csv")["bmi"].dropna()
print(f"@bmi_distribution[{'normal' if abs(x.skew()) < 0.5 else 'not_normal'}]")
""",
)
correct(
    33,
    """
import pandas as pd
from scipy.stats import kstest
x = pd.read_csv("imp.score.ldlr.metabolome.csv")["row m/z"].dropna()
p = kstest((x - x.mean()) / x.std(), "norm").pvalue
print(f"@ks_test_p_value[{p:.4f}] @normality_decision[{'normally distributed' if p >= 0.05 else 'not normally distributed'}]")
""",
)
correct(
    57,
    """
import pandas as pd
df = pd.read_csv("estimated_numbers.csv")
a = pd.to_numeric(df["No. of cases"].astype(str).str.split("[").str[0], errors="coerce")
b = pd.to_numeric(df["No. of deaths"].astype(str).str.split("[").str[0], errors="coerce")
ok = a.notna() & b.notna()
print(f"@correlation_coefficient[{a[ok].corr(b[ok]):.2f}]")
""",
)
correct(
    59,
    """
import pandas as pd
df = pd.read_csv("estimated_numbers.csv")
df["cases"] = pd.to_numeric(df["No. of cases"].astype(str).str.split("[").str[0], errors="coerce")
d = df[df["WHO Region"].str.strip().str.lower() == "americas"].dropna(subset=["cases"])
print(f"@country_name[{d.groupby('Country')['cases'].mean().idxmax()}]")
""",
)
correct(
    243,
    """
import pandas as pd
x = pd.read_csv("baseball_data.csv")["batting_average"].dropna()
print(f"@mean_batting_average[{x.mean():.3f}]")
""",
)
correct(
    255,
    """
import pandas as pd
x = pd.read_csv("gapminder_gdp_asia.csv")["gdpPercap_2007"]
print(f"@mean_gdp2007[{x.mean():.2f}] @standard_deviation_gdp2007[{x.std():.2f}]")
""",
)
correct(
    320,
    """
import pandas as pd
x = pd.read_csv("0020200722.csv")["EVENTMSGTYPE"]
print(f"@mean_eventmsgtype[{x.mean()}]")
""",
)
correct(
    354,
    """
import pandas as pd
df = pd.read_csv("test_x.csv")
print(f"@average_familysize[{(df['IsAlone'] + 2).mean():.1f}]")
""",
)
correct(
    425,
    """
import pandas as pd
df = pd.read_csv("cost_data_with_errors.csv")
print(f"@missing_values_count[{df['max_sust_wind'].isnull().sum()}]")
""",
)
correct(
    474,
    """
import pandas as pd
df = pd.read_csv("oecd_education_spending.csv").dropna(subset=["Value", "TIME"])
print(f"@correlation_coefficient[{df['Value'].corr(df['TIME']):.2f}]")
""",
)
correct(
    490,
    """
import pandas as pd
x = pd.read_csv("percent-bachelors-degrees-women-usa.csv")["Engineering"]
print(f"@mean_value[{x.mean():.2f}]")
""",
)
correct(
    578,
    """
import pandas as pd
x = pd.read_csv("e5_aapl.csv")["Volume"]
print(f"@mean_volume[{x.mean():.2f}]")
""",
)
correct(
    710,
    """
import pandas as pd
x = pd.to_numeric(pd.read_csv("Current_Logan.csv")["JAMES LOGAN"], errors="coerce").dropna()
print(f"@mean_wins[{x.mean()}]")
""",
)
correct(
    108,
    """
import pandas as pd
df = pd.read_csv("test_Y3wMUE5_7gLdaTN.csv")
t = df["ApplicantIncome"] + df["CoapplicantIncome"]
print(f"@mean_total_income[{t.mean():.2f}] @std_dev_total_income[{t.std():.2f}]")
""",
)
correct(
    116,
    """
import pandas as pd
df = pd.read_csv("2015.csv")
s = df["Happiness Score"]
z = (s - s.mean()) / s.std(ddof=0)
print("@outlier_countries[" + ",".join(df[abs(z) > 3]["Country"]) + "]")
""",
)
correct(
    254,
    """
import pandas as pd
df = pd.read_csv("gapminder_gdp_asia.csv")
x = df["gdpPercap_1982"]
q1, q3 = x.quantile(0.25), x.quantile(0.75)
i = q3 - q1
out = df[(x < q1 - 1.5 * i) | (x > q3 + 1.5 * i)]["country"]
print("@outlier_countries[" + ", ".join(out) + "]")
""",
)
correct(
    375,
    """
import pandas as pd
from scipy import stats
x = pd.read_csv("2014_q4.csv")["Trips over the past 24-hours (midnight to 11:59pm)"].dropna()
w, p = stats.shapiro(x)
print(f"@shapiro_w[{w:.4f}] @p_value[{p:.4f}] @skewness[{stats.skew(x):.4f}] @kurtosis[{stats.kurtosis(x):.4f}]")
""",
)
correct(
    421,
    """
import pandas as pd
v = pd.to_numeric(pd.read_csv("bitconnect_price.csv")["Volume"].str.replace(",", ""))
print(f"@mean_volume[{v.mean():.2f}] @median_volume[{v.median():.2f}]")
""",
)
correct(
    426,
    """
import pandas as pd
df = pd.read_csv("cost_data_with_errors.csv")
row = df.loc[df["max_storm_cat"].idxmax()]
print(f"@max_wind_speed[{row['max_sust_wind']}]")
""",
)
correct(
    508,
    """
import pandas as pd
df = pd.read_csv("hotel_data.csv").dropna(subset=["review_count", "bubble_score"])
print(f"@correlation_coefficient[{df['review_count'].corr(df['bubble_score']):.3f}]")
""",
)
correct(
    510,
    """
import pandas as pd
df = pd.read_csv("hotel_data.csv")
n = df.dropna(subset=["brand_name"]).groupby("brand_name").size()
ok = n[n >= 10].index
d = df[(df["review_count"] >= 100) & df["brand_name"].isin(ok)].dropna(subset=["star_rating"])
t = d.groupby("brand_name")["star_rating"].mean().to_frame("m")
t["n"] = n.reindex(t.index)
print(f"@brand_with_highest_average_star_rating[{t.sort_values(['m', 'n'], ascending=False).index[0]}]")
""",
)
correct(
    587,
    """
import pandas as pd
df = pd.read_csv("20170413_000000_group_statistics.csv")
h = df["avg. wait time "].str.split(":", expand=True).astype(int)
sec = h[0] * 3600 + h[1] * 60 + h[2]
print(f"@correlation_coefficient[{df['avg. num. agents talking '].corr(sec):.3f}]")
""",
)
correct(
    651,
    """
import pandas as pd
z = pd.read_csv("DES=+2006261.csv")["Z"]
q1, q3 = z.quantile(0.25), z.quantile(0.75)
print(f"@outlier_count[{((z < q1 - 1.5 * (q3 - q1)) | (z > q3 + 1.5 * (q3 - q1))).sum()}]")
""",
)
correct(
    652,
    """
import pandas as pd
from scipy.stats import normaltest
p = normaltest(pd.read_csv("DES=+2006261.csv")["X"].dropna()).pvalue
print(f"@normality_test_p_value[{p:.4f}] @normal_distribution[{p >= 0.05}]")
""",
)
correct(
    716,
    """
import pandas as pd
x = pd.to_numeric(pd.read_csv("Current_Logan.csv")["JAMES LOGAN"], errors="coerce").dropna()
print(f"@mean_wins[{x.mean():.2f}] @stddev_wins[{x.std():.2f}]")
""",
)
correct(
    730,
    """
import pandas as pd
from scipy.stats import pearsonr
df = pd.read_csv("gapminder_cleaned.csv")
r, p = pearsonr(df["pop"], df["gdppercap"])
print(f"@correlation_coefficient[{r:.2f}] @p_value[{p:.4f}]")
""",
)
correct(
    740,
    """
import pandas as pd
b = pd.read_csv("Credit.csv")["Balance"]
print(f"@outliers[{((b - b.mean()).abs() > 3 * b.std(ddof=0)).sum()}]")
""",
)
correct(
    28,
    """
import pandas as pd
df = pd.read_csv("insurance.csv").dropna(subset=["age", "sex", "region"])
df["sex"] = df["sex"].map({"female": 0, "male": 1})
df["smoker"] = df["smoker"].map({"no": 0, "yes": 1})
df["region"] = df["region"].astype("category").cat.codes
for c in ["age", "bmi", "children", "charges"]:
    df[c] = (df[c] - df[c].min()) / (df[c].max() - df[c].min())
print(" ".join(f"@mean_{c}[{df[c].mean():.4f}]" for c in ["age", "sex", "bmi", "children", "smoker", "region", "charges"]))
""",
)
correct(
    39,
    """
import numpy as np
import pandas as pd
from scipy.stats import shapiro
x = pd.read_csv("imp.score.ldlr.metabolome.csv")["importance.score"].dropna()
p = shapiro(x).pvalue
if p < 0.05:
    x = np.log(x[x > 0])
print(f"@is_normal[{p:.4f}] @transformed_importance_score_mean[{x.mean():.2f}] @transformed_importance_score_std[{x.std():.2f}]")
""",
)
correct(
    109,
    """
import pandas as pd
from scipy.stats import ttest_ind
df = pd.read_csv("test_Y3wMUE5_7gLdaTN.csv")
edu = df["Education"].str.strip().str.lower()
g = df[edu == "graduate"]["LoanAmount"].dropna()
n = df[edu == "not graduate"]["LoanAmount"].dropna()
s = "significant" if ttest_ind(g, n).pvalue < 0.05 else "no significant"
print(f"@graduate_mean_loan[{g.mean():.2f}] @not_graduate_mean_loan[{n.mean():.2f}] @significance[{s}]")
""",
)
correct(
    111,
    """
import pandas as pd
df = pd.read_csv("test_Y3wMUE5_7gLdaTN.csv")
df["Self_Employed"] = df["Self_Employed"].fillna("No")
x = df["LoanAmount"].fillna(df["LoanAmount"].median())
print(f"@mean_loan[{x.mean():.2f}] @median_loan[{x.median():.2f}] @std_dev_loan[{x.std():.2f}]")
""",
)
correct(
    133,
    """
import pandas as pd
df = pd.read_csv("titanic.csv").dropna(subset=["Cabin"])
print(f"@row_count[{len(df)}] @median_age[{df['Age'].median():.1f}]")
""",
)
correct(
    177,
    """
import pandas as pd
from scipy.stats import mannwhitneyu
df = pd.read_csv("titanic.csv")
a = df[df["Pclass"] == 1]["Age"].dropna()
b = df[df["Pclass"] == 3]["Age"].dropna()
p = mannwhitneyu(a, b).pvalue
print(f"@p_value[{p:.4f}] @significance[{'Yes' if p < 0.05 else 'No'}]")
""",
)
correct(
    309,
    """
import pandas as pd
from scipy.stats import skew, kurtosis
df = pd.read_csv("titanic.csv")
out = []
for name, col in (("age", "Age"), ("fare", "Fare")):
    x = df[col].dropna()
    inside = ((x >= x.mean() - x.std()) & (x <= x.mean() + x.std())).sum()
    out.append(f"@{name}_skewness[{skew(x)}] @{name}_kurtosis[{kurtosis(x)}] @{name}_values_within_one_stdev[{inside}]")
print(" ".join(out))
""",
)
correct(
    423,
    """
import pandas as pd
df = pd.read_csv("bitconnect_price.csv")
v = pd.to_numeric(df["Volume"].str.replace(",", ""))
r = ((df["High"] - df["Low"]) / df["Open"]).corr(v)
t = "positive" if r >= 0.5 else "negative" if r <= -0.5 else "none"
print(f"@correlation_coefficient[{r:.2f}] @relationship_type[{t}]")
""",
)
correct(
    619,
    """
import pandas as pd
d = pd.read_csv("traj-Osak.csv")["poiDuration"].astype(float)
z = (d - d.mean()) / d.std(ddof=0)
k = d[abs(z) <= 2.5]
print(f"@mean_new[{k.mean():.2f}] @std_dev_new[{k.std():.2f}]")
""",
)
correct(
    647,
    """
import pandas as pd
from scipy.stats import shapiro
df = pd.read_csv("random_stock_data.csv")
r = (df["High"] - df["Low"]).dropna()
p = shapiro(r).pvalue
print(f"@price_range_mean[{r.mean():.2f}] @price_range_stddev[{r.std():.2f}] @price_range_p_value[{p:.4f}] @is_normal[{'yes' if p > 0.05 else 'no'}]")
""",
)
correct(
    656,
    """
import pandas as pd
x = pd.read_csv("DES=+2006261.csv")["X"]
z = (x - x.mean()) / x.std(ddof=0)
k = x[abs(z) <= 3]
print(f"@number_of_outliers[{(abs(z) > 3).sum()}] @new_mean[{k.mean():.2f}] @new_standard_deviation[{k.std():.2f}]")
""",
)
correct(
    723,
    """
import pandas as pd
df = pd.read_csv("auto-mpg.csv")
r = (pd.to_numeric(df["horsepower"], errors="coerce") / pd.to_numeric(df["weight"], errors="coerce")).dropna()
print(f"@mean_ratio[{r.mean():.2f}] @std_ratio[{r.std(ddof=0):.2f}]")
""",
)
correct(
    725,
    """
import pandas as pd
df = pd.read_csv("auto-mpg.csv")
out = []
for n, d in enumerate(df["displacement"].value_counts().index[:3], 1):
    m = df[df["displacement"] == d]["mpg"]
    out.append(f"@mean{n}[{m.mean():.2f}] @median{n}[{m.median():.2f}]")
print(" ".join(out))
""",
)
correct(
    734,
    """
import pandas as pd
from scipy.stats import pearsonr
df = pd.read_csv("gapminder_cleaned.csv")
for name, g in df.groupby("continent"):
    r, p = pearsonr(g["lifeexp"], g["gdppercap"])
    kind = "significant" if p < 0.05 and abs(r) >= 0.5 else "non-significant"
    print(f"@continent_name[{name}] @correlation_coefficient[{r:.2f}] @p_value[{p:.4f}] @correlation_significance[{kind}]")
""",
)

# (task, kind, old text, new text). Applied to CORRECT[task]; `old` must occur exactly once.
MISTAKES: list[tuple[int, str, str, str]] = [
    (19, "M1_dropna_forgotten", '["Mar.2020"].dropna()', '["Mar.2020"]'),
    (25, "M1_dropna_forgotten", '["bmi"].dropna()', '["bmi"]'),
    (33, "M1_dropna_forgotten", '["row m/z"].dropna()', '["row m/z"]'),
    (243, "M1_dropna_forgotten", '["batting_average"].dropna()', '["batting_average"].fillna(0)'),
    (474, "M1_dropna_forgotten", '.dropna(subset=["Value", "TIME"])', ""),
    (508, "M1_dropna_forgotten", '.dropna(subset=["review_count", "bubble_score"])', ""),
    (710, "M1_dropna_forgotten", ".dropna()\nprint", ".fillna(0)\nprint"),
    (716, "M1_dropna_forgotten", ".dropna()\nprint", ".fillna(0)\nprint"),
    (
        375,
        "M1_dropna_forgotten",
        '"Trips over the past 24-hours (midnight to 11:59pm)"].dropna()',
        '"Trips over the past 24-hours (midnight to 11:59pm)"]',
    ),
    (652, "M1_dropna_forgotten", '["X"].dropna()', '["X"]'),
    (109, "M1_dropna_forgotten", '["LoanAmount"].dropna()\nn =', '["LoanAmount"].fillna(0)\nn ='),
    (177, "M1_dropna_forgotten", '["Age"].dropna()\nb', '["Age"].fillna(0)\nb'),
    (309, "M1_dropna_forgotten", "x = df[col].dropna()", "x = df[col].fillna(0)"),
    (647, "M1_dropna_forgotten", ".dropna()\np", "\np"),
    (39, "M1_dropna_forgotten", '["importance.score"].dropna()', '["importance.score"]'),
    (59, "M1_dropna_forgotten", '.dropna(subset=["cases"])', '.fillna({"cases": 0})'),
    (243, "M2_truncated", "{x.mean():.3f}", "{int(x.mean() * 1000) / 1000:.3f}"),
    (255, "M2_truncated", "{x.mean():.2f}", "{int(x.mean()):.2f}"),
    (320, "M2_truncated", "{x.mean()}", "{int(x.mean())}"),
    (490, "M2_truncated", "{x.mean():.2f}", "{int(x.mean()):.2f}"),
    (578, "M2_truncated", "{x.mean():.2f}", "{int(x.mean()):.2f}"),
    (108, "M2_truncated", "{t.std():.2f}", "{int(t.std()):.2f}"),
    (111, "M2_truncated", "{x.mean():.2f}", "{int(x.mean()):.2f}"),
    (354, "M2_truncated", "(df['IsAlone'] + 2).mean():.1f", "int((df['IsAlone'] + 2).mean()):.1f"),
    (723, "M2_truncated", "{r.mean():.2f}", "{int(r.mean() * 100) / 100:.2f}"),
    (255, "M3_median_for_mean", "{x.mean():.2f}", "{x.median():.2f}"),
    (243, "M3_median_for_mean", "{x.mean():.3f}", "{x.median():.3f}"),
    (490, "M3_median_for_mean", "{x.mean():.2f}", "{x.median():.2f}"),
    (578, "M3_median_for_mean", "{x.mean():.2f}", "{x.median():.2f}"),
    (421, "M3_median_for_mean", "{v.mean():.2f}", "{v.median():.2f}"),
    (108, "M3_median_for_mean", "{t.mean():.2f}", "{t.median():.2f}"),
    (320, "M3_median_for_mean", "{x.mean()}", "{x.median()}"),
    (
        426,
        "M4_unstable_head",
        'df.loc[df["max_storm_cat"].idxmax()]',
        'df.sort_values("max_storm_cat", ascending=False, kind="quicksort").iloc[0]',
    ),
    (
        59,
        "M4_unstable_head",
        "d.groupby('Country')['cases'].mean().idxmax()",
        "d.groupby('Country')['cases'].mean().sort_values(ascending=False, kind='quicksort').index[0]",
    ),
    (
        510,
        "M4_unstable_head",
        "t.sort_values(['m', 'n'], ascending=False)",
        "t.sort_values(['m'], ascending=False, kind='quicksort')",
    ),
    (
        725,
        "M4_unstable_head",
        'df["displacement"].value_counts().index[:3]',
        'df["displacement"].value_counts(sort=False).sort_values(ascending=False, kind="quicksort").index[:3]',
    ),
    (
        59,
        "M5_case_sensitive",
        'df["WHO Region"].str.strip().str.lower() == "americas"',
        'df["WHO Region"] == "Americas"',
    ),
]
