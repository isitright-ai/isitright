# Proposed fixture: pending owner review
"""Gold programs for the selected InfiAgent-DABench questions (see select_tasks.py).

Written by Claude (the author of the pack under test) from the question text, the constraints text
and the answer format; accepted only if they reproduce the benchmark's recorded answer on the
unmutated data (see accept_gold.py). Each program reads its data file by name, computes the answer
and assigns ``result``, a mapping from the format's answer names to values. A program here is an
implementation of the task, not the task: where the question is ambiguous the interpretation is
written in a comment.

The benchmark's labels were not used to write these, only to accept or reject them.
"""

GOLD: dict[int, tuple[str, str]] = {}  # question id -> (data file, program)


def gold(question: int, file: str, code: str) -> None:
    GOLD[question] = (file, code.strip() + "\n")


gold(
    19,
    "unemployement_industry.csv",
    """
import pandas as pd
from scipy import stats
df = pd.read_csv("unemployement_industry.csv")
skew = round(float(stats.skew(df["Mar.2020"].dropna())), 2)  # Fisher-Pearson, biased
result = {"is_normal": "Yes" if -0.5 <= skew <= 0.5 else "No"}
""",
)

gold(
    25,
    "insurance.csv",
    """
import pandas as pd
df = pd.read_csv("insurance.csv")
skew = df["bmi"].dropna().skew()  # "Python's built-in function": pandas Series.skew
result = {"bmi_distribution": "normal" if abs(skew) < 0.5 else "not_normal"}
""",
)

gold(
    33,
    "imp.score.ldlr.metabolome.csv",
    """
import pandas as pd
from scipy import stats
df = pd.read_csv("imp.score.ldlr.metabolome.csv")
x = df["row m/z"].dropna()
p = stats.kstest((x - x.mean()) / x.std(), "norm").pvalue  # against a normal with fitted parameters
result = {
    "ks_test_p_value": round(float(p), 4),
    "normality_decision": "normally distributed" if p >= 0.05 else "not normally distributed",
}
""",
)

gold(
    57,
    "estimated_numbers.csv",
    """
import pandas as pd
df = pd.read_csv("estimated_numbers.csv")
# Values look like "630308[495000-801000]": the number before the bracket is the estimate.
cases = pd.to_numeric(df["No. of cases"].astype(str).str.split("[").str[0].str.strip(), errors="coerce")
deaths = pd.to_numeric(df["No. of deaths"].astype(str).str.split("[").str[0].str.strip(), errors="coerce")
pair = pd.concat([cases, deaths], axis=1).dropna()
result = {"correlation_coefficient": round(float(pair.iloc[:, 0].corr(pair.iloc[:, 1])), 2)}
""",
)

gold(
    59,
    "estimated_numbers.csv",
    """
import pandas as pd
df = pd.read_csv("estimated_numbers.csv")
df["cases"] = pd.to_numeric(df["No. of cases"].astype(str).str.split("[").str[0].str.strip(), errors="coerce")
americas = df[df["WHO Region"] == "Americas"].dropna(subset=["cases"])
result = {"country_name": americas.groupby("Country")["cases"].mean().idxmax()}
""",
)

gold(
    243,
    "baseball_data.csv",
    """
import pandas as pd
df = pd.read_csv("baseball_data.csv")
result = {"mean_batting_average": round(float(df["batting_average"].dropna().mean()), 3)}
""",
)

gold(
    255,
    "gapminder_gdp_asia.csv",
    """
import pandas as pd
df = pd.read_csv("gapminder_gdp_asia.csv")
col = df["gdpPercap_2007"]
result = {
    "mean_gdp2007": round(float(col.mean()), 2),
    "standard_deviation_gdp2007": round(float(col.std()), 2),  # sample standard deviation
}
""",
)

gold(
    320,
    "0020200722.csv",
    """
import pandas as pd
df = pd.read_csv("0020200722.csv")
result = {"mean_eventmsgtype": float(df["EVENTMSGTYPE"].mean())}
""",
)

gold(
    354,
    "test_x.csv",
    """
import pandas as pd
df = pd.read_csv("test_x.csv")
family = df["IsAlone"] + 1 + 1
result = {"average_familysize": round(float(family.mean()), 1)}
""",
)

gold(
    425,
    "cost_data_with_errors.csv",
    """
import pandas as pd
df = pd.read_csv("cost_data_with_errors.csv")
result = {"missing_values_count": int(df["max_sust_wind"].isna().sum())}
""",
)

gold(
    474,
    "oecd_education_spending.csv",
    """
import pandas as pd
df = pd.read_csv("oecd_education_spending.csv")
pair = df[["Value", "TIME"]].dropna()
result = {"correlation_coefficient": round(float(pair["Value"].corr(pair["TIME"])), 2)}
""",
)

gold(
    490,
    "percent-bachelors-degrees-women-usa.csv",
    """
import pandas as pd
df = pd.read_csv("percent-bachelors-degrees-women-usa.csv")
result = {"mean_value": round(float(df["Engineering"].mean()), 2)}
""",
)

gold(
    578,
    "e5_aapl.csv",
    """
import pandas as pd
df = pd.read_csv("e5_aapl.csv")
result = {"mean_volume": round(float(df["Volume"].mean()), 2)}
""",
)

gold(
    710,
    "Current_Logan.csv",
    """
import pandas as pd
df = pd.read_csv("Current_Logan.csv")
wins = pd.to_numeric(df["JAMES LOGAN"], errors="coerce").dropna()
result = {"mean_wins": float(wins.mean())}
""",
)

gold(
    108,
    "test_Y3wMUE5_7gLdaTN.csv",
    """
import pandas as pd
df = pd.read_csv("test_Y3wMUE5_7gLdaTN.csv")
total = df["ApplicantIncome"] + df["CoapplicantIncome"]
result = {
    "mean_total_income": round(float(total.mean()), 2),
    "std_dev_total_income": round(float(total.std()), 2),
}
""",
)

gold(
    116,
    "2015.csv",
    """
import pandas as pd
df = pd.read_csv("2015.csv")
score = df["Happiness Score"]
z = (score - score.mean()) / score.std(ddof=0)  # population standard deviation
result = {"outlier_countries": sorted(df.loc[z.abs() > 3, "Country"].tolist())}
""",
)

gold(
    254,
    "gapminder_gdp_asia.csv",
    """
import pandas as pd
df = pd.read_csv("gapminder_gdp_asia.csv")
col = df["gdpPercap_1982"]
q1, q3 = col.quantile(0.25), col.quantile(0.75)
iqr = q3 - q1
mask = (col < q1 - 1.5 * iqr) | (col > q3 + 1.5 * iqr)
result = {"outlier_countries": sorted(df.loc[mask, "country"].tolist())}
""",
)

gold(
    375,
    "2014_q4.csv",
    """
import pandas as pd
from scipy import stats
df = pd.read_csv("2014_q4.csv")
x = df["Trips over the past 24-hours (midnight to 11:59pm)"].dropna()
w, p = stats.shapiro(x)
result = {
    "shapiro_w": round(float(w), 4),
    "p_value": round(float(p), 4),
    "skewness": round(float(stats.skew(x)), 4),
    "kurtosis": round(float(stats.kurtosis(x)), 4),
}
""",
)

gold(
    421,
    "bitconnect_price.csv",
    """
import pandas as pd
df = pd.read_csv("bitconnect_price.csv")
volume = pd.to_numeric(df["Volume"].astype(str).str.replace(",", ""), errors="coerce")
result = {
    "mean_volume": round(float(volume.mean()), 2),
    "median_volume": round(float(volume.median()), 2),
}
""",
)

gold(
    426,
    "cost_data_with_errors.csv",
    """
import pandas as pd
df = pd.read_csv("cost_data_with_errors.csv")
top = df.loc[df["max_storm_cat"].idxmax()]  # first row of the highest category
result = {"max_wind_speed": float(top["max_sust_wind"])}
""",
)

gold(
    508,
    "hotel_data.csv",
    """
import pandas as pd
df = pd.read_csv("hotel_data.csv")
pair = df[["review_count", "bubble_score"]].dropna()
result = {"correlation_coefficient": round(float(pair["review_count"].corr(pair["bubble_score"])), 3)}
""",
)

gold(
    510,
    "hotel_data.csv",
    """
import pandas as pd
df = pd.read_csv("hotel_data.csv")
sizes = df.dropna(subset=["brand_name"]).groupby("brand_name").size()
brands = sizes[sizes >= 10].index
rated = df[(df["review_count"] >= 100) & df["brand_name"].isin(brands)].dropna(subset=["star_rating"])
table = rated.groupby("brand_name")["star_rating"].mean().to_frame("mean")
table["hotels"] = sizes.reindex(table.index)
best = table.sort_values(["mean", "hotels"], ascending=[False, False]).index[0]
result = {"brand_with_highest_average_star_rating": best}
""",
)

gold(
    587,
    "20170413_000000_group_statistics.csv",
    """
import pandas as pd
df = pd.read_csv("20170413_000000_group_statistics.csv")
parts = df["avg. wait time "].astype(str).str.split(":", expand=True).astype(float)
seconds = (parts[0] * 3600 + parts[1] * 60 + parts[2]).astype(int)
corr = df["avg. num. agents talking "].corr(seconds)
result = {"correlation_coefficient": round(float(corr), 3)}
""",
)

gold(
    651,
    "DES=+2006261.csv",
    """
import pandas as pd
df = pd.read_csv("DES=+2006261.csv")
z = df["Z"]
q1, q3 = z.quantile(0.25), z.quantile(0.75)
iqr = q3 - q1
result = {"outlier_count": int(((z < q1 - 1.5 * iqr) | (z > q3 + 1.5 * iqr)).sum())}
""",
)

gold(
    652,
    "DES=+2006261.csv",
    """
import pandas as pd
from scipy import stats
df = pd.read_csv("DES=+2006261.csv")
p = float(stats.normaltest(df["X"].dropna()).pvalue)
result = {"normality_test_p_value": round(p, 4), "normal_distribution": str(p >= 0.05)}
""",
)

gold(
    716,
    "Current_Logan.csv",
    """
import pandas as pd
df = pd.read_csv("Current_Logan.csv")
wins = pd.to_numeric(df["JAMES LOGAN"], errors="coerce").dropna()
result = {"mean_wins": round(float(wins.mean()), 2), "stddev_wins": round(float(wins.std()), 2)}
""",
)

gold(
    730,
    "gapminder_cleaned.csv",
    """
import pandas as pd
from scipy import stats
df = pd.read_csv("gapminder_cleaned.csv")
r, p = stats.pearsonr(df["pop"], df["gdppercap"])
result = {"correlation_coefficient": round(float(r), 2), "p_value": round(float(p), 4)}
""",
)

gold(
    740,
    "Credit.csv",
    """
import pandas as pd
df = pd.read_csv("Credit.csv")
b = df["Balance"]
z = (b - b.mean()) / b.std(ddof=0)
result = {"outliers": int((z.abs() > 3).sum())}
""",
)

gold(
    28,
    "insurance.csv",
    """
import pandas as pd
df = pd.read_csv("insurance.csv").dropna(subset=["age", "sex", "region"])
df["sex"] = (df["sex"] == "male").astype(int)
df["smoker"] = (df["smoker"] == "yes").astype(int)
df["region"] = df["region"].astype("category").cat.codes
for col in ["age", "bmi", "children", "charges"]:  # min-max normalisation
    df[col] = (df[col] - df[col].min()) / (df[col].max() - df[col].min())
result = {f"mean_{c}": round(float(df[c].mean()), 4) for c in
          ["age", "sex", "bmi", "children", "smoker", "region", "charges"]}
""",
)

gold(
    39,
    "imp.score.ldlr.metabolome.csv",
    """
import numpy as np
import pandas as pd
from scipy import stats
df = pd.read_csv("imp.score.ldlr.metabolome.csv")
x = df["importance.score"].dropna()
p = float(stats.shapiro(x).pvalue)
if p < 0.05:
    x = np.log(x[x > 0])
result = {
    "is_normal": round(p, 4),
    "transformed_importance_score_mean": round(float(x.mean()), 2),
    "transformed_importance_score_std": round(float(x.std()), 2),
}
""",
)

gold(
    109,
    "test_Y3wMUE5_7gLdaTN.csv",
    """
import pandas as pd
from scipy import stats
df = pd.read_csv("test_Y3wMUE5_7gLdaTN.csv")
grad = df.loc[df["Education"] == "Graduate", "LoanAmount"].dropna()
other = df.loc[df["Education"] == "Not Graduate", "LoanAmount"].dropna()
p = stats.ttest_ind(grad, other).pvalue
result = {
    "graduate_mean_loan": round(float(grad.mean()), 2),
    "not_graduate_mean_loan": round(float(other.mean()), 2),
    "significance": "significant" if p < 0.05 else "no significant",
}
""",
)

gold(
    111,
    "test_Y3wMUE5_7gLdaTN.csv",
    """
import pandas as pd
df = pd.read_csv("test_Y3wMUE5_7gLdaTN.csv")
df["Self_Employed"] = df["Self_Employed"].fillna("No")
loan = df["LoanAmount"].fillna(df["LoanAmount"].median())
result = {
    "mean_loan": round(float(loan.mean()), 2),
    "median_loan": round(float(loan.median()), 2),
    "std_dev_loan": round(float(loan.std()), 2),
}
""",
)

gold(
    133,
    "titanic.csv",
    """
import pandas as pd
df = pd.read_csv("titanic.csv")
df = df.dropna(subset=["Cabin"])
median_age = float(df["Age"].median())  # of the passengers left after the deletion
result = {"row_count": int(len(df)), "median_age": round(median_age, 1)}
""",
)

gold(
    177,
    "titanic.csv",
    """
import pandas as pd
from scipy import stats
df = pd.read_csv("titanic.csv")
first = df.loc[df["Pclass"] == 1, "Age"].dropna()
third = df.loc[df["Pclass"] == 3, "Age"].dropna()
p = float(stats.mannwhitneyu(first, third, alternative="two-sided").pvalue)
result = {"p_value": round(p, 4), "significance": "Yes" if p < 0.05 else "No"}
""",
)

gold(
    309,
    "titanic.csv",
    """
import pandas as pd
from scipy import stats
df = pd.read_csv("titanic.csv")
result = {}
for name, col in (("age", "Age"), ("fare", "Fare")):
    x = df[col].dropna()
    result[f"{name}_skewness"] = float(stats.skew(x))
    result[f"{name}_kurtosis"] = float(stats.kurtosis(x))
    result[f"{name}_values_within_one_stdev"] = int(((x >= x.mean() - x.std()) & (x <= x.mean() + x.std())).sum())
""",
)

gold(
    423,
    "bitconnect_price.csv",
    """
import pandas as pd
df = pd.read_csv("bitconnect_price.csv")
volume = pd.to_numeric(df["Volume"].astype(str).str.replace(",", ""), errors="coerce")
volatility = (df["High"] - df["Low"]) / df["Open"]
r = float(volatility.corr(volume))
kind = "positive" if r >= 0.5 else "negative" if r <= -0.5 else "none"
result = {"correlation_coefficient": round(r, 2), "relationship_type": kind}
""",
)

gold(
    619,
    "traj-Osak.csv",
    """
import pandas as pd
df = pd.read_csv("traj-Osak.csv")
d = df["poiDuration"].astype(float)  # a visit's duration (endTime - startTime)
z = (d - d.mean()) / d.std(ddof=0)
kept = d[z.abs() <= 2.5]
result = {"mean_new": round(float(kept.mean()), 2), "std_dev_new": round(float(kept.std()), 2)}
""",
)

gold(
    647,
    "random_stock_data.csv",
    """
import pandas as pd
from scipy import stats
df = pd.read_csv("random_stock_data.csv")
price_range = df["High"] - df["Low"]
p = float(stats.shapiro(price_range.dropna()).pvalue)
result = {
    "price_range_mean": round(float(price_range.mean()), 2),
    "price_range_stddev": round(float(price_range.std()), 2),
    "price_range_p_value": round(p, 4),
    "is_normal": "yes" if p > 0.05 else "no",
}
""",
)

gold(
    656,
    "DES=+2006261.csv",
    """
import pandas as pd
df = pd.read_csv("DES=+2006261.csv")
x = df["X"]
z = (x - x.mean()) / x.std(ddof=0)
kept = x[z.abs() <= 3]
result = {
    "number_of_outliers": int((z.abs() > 3).sum()),
    "new_mean": round(float(kept.mean()), 2),
    "new_standard_deviation": round(float(kept.std()), 2),
}
""",
)

gold(
    723,
    "auto-mpg.csv",
    """
import pandas as pd
df = pd.read_csv("auto-mpg.csv")
horsepower = pd.to_numeric(df["horsepower"], errors="coerce")
weight = pd.to_numeric(df["weight"], errors="coerce")
ratio = (horsepower / weight).dropna()
result = {"mean_ratio": round(float(ratio.mean()), 2), "std_ratio": round(float(ratio.std(ddof=0)), 2)}
""",
)

gold(
    725,
    "auto-mpg.csv",
    """
import pandas as pd
df = pd.read_csv("auto-mpg.csv")
top = df["displacement"].value_counts().index[:3]
result = {}
for n, value in enumerate(top, 1):
    mpg = df.loc[df["displacement"] == value, "mpg"]
    result[f"mean{n}"] = round(float(mpg.mean()), 2)
    result[f"median{n}"] = round(float(mpg.median()), 2)
""",
)

gold(
    734,
    "gapminder_cleaned.csv",
    """
import pandas as pd
from scipy import stats
df = pd.read_csv("gapminder_cleaned.csv")
result = {}
for continent, part in df.groupby("continent"):
    r, p = stats.pearsonr(part["lifeexp"], part["gdppercap"])
    kind = "significant" if p < 0.05 and abs(r) >= 0.5 else "non-significant"
    result[f"{continent}"] = {
        "correlation_coefficient": round(float(r), 2),
        "p_value": round(float(p), 4),
        "correlation_significance": kind,
    }
""",
)
